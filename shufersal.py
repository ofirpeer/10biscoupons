#  email setup:
#  change sender_email and receiver_email to the email you want it sent from and received in
#  Update the smtp:
#         fields smtp_server = 'smtp.example.com' - for gmail mail change example to gmail
#         smtp_port = 587 - depends on provider (587 is gmail)
#         smtp_password = 'your_password' - use app passwords ( gmail example https://support.google.com/mail/answer/185833?hl=en)

#  run the script with the --send-email flag

import argparse
import threading
import time
import http.client
import http.cookiejar
import itertools
import json
import os
import shutil
import urllib.request
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import ssl


class Shufersal:
    def __init__(self, months_back=12):
        self.script_args = self._load_script_args()
        self.unused_barcodes = []
        self.output_dir = "barcodes"
        self.months_back = months_back
        self.shufersal_transactions = []
        self.shufersal_restaurant_id = 26698
        self.context = ssl._create_unverified_context()
        cookie_str = self.login()

        self.headers = {
            'Content-Type': 'application/json',
            'Cookie': cookie_str
        }

    def _load_script_args(self):
        parser = argparse.ArgumentParser(description='Fetch unused Shufersal barcodes from 10Bis')
        parser.add_argument('--email', type=str, help='Email address of the 10Bis account')
        parser.add_argument('--send-email', action='store_true', help='Send an email with the barcodes')
        return parser.parse_args()

    def parse_cookies(self, headers):
        cookies = {}
        for header_name, header_value in headers:
            if header_name.lower() == "set-cookie":
                cookie_values = header_value.split(";")
                cookie = cookie_values[0].split("=", 1)
                cookie_name = cookie[0].strip()
                cookie_value = cookie[1].strip()
                cookies[cookie_name] = cookie_value

        return "; ".join([f"{name}={value}" for name, value in cookies.items()])

    def request_otp(self, email):
        headers = {
            "accept": "application/json, text/plain, */*",
            "content-type": "application/json",
        }
        data = {
            "culture": "he-IL",
            "uiCulture": "he",
            "email": email
        }

        body = json.dumps(data)

        with closing(http.client.HTTPSConnection("www.10bis.co.il", context=self.context)) as conn:
            conn.request("POST", "/NextApi/GetUserAuthenticationDataAndSendAuthenticationCodeToUser", body, headers)
            response = conn.getresponse()
            response_data = response.read().decode("utf-8")
            response_json = json.loads(response_data)
            # Extract authenticationToken
            authentication_token = response_json["Data"]["codeAuthenticationData"]["authenticationToken"]

        return authentication_token

    def verify_otp(self, email, authentication_token):
        otp = input("Enter otp sent to your mobile phone: ")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/plain, */*",
        }
        data = {
            "culture": "he-IL",
            "uiCulture": "he",
            "email": email,
            "authenticationToken": authentication_token,
            "authenticationCode": otp
        }
        body = json.dumps(data)

        with closing(http.client.HTTPSConnection("www.10bis.co.il", context=self.context)) as conn:
            conn.request("POST", "/NextApi/GetUserV2", body, headers)
            response = conn.getresponse()
            cookie_str = self.parse_cookies(response.getheaders())

        return cookie_str

    def login(self):
        email = self._get_email()
        authentication_token = self.request_otp(email)
        cookie_str = self.verify_otp(email, authentication_token)
        return cookie_str

    def _get_email(self):
        email = self.script_args.email

        if not email:
            email = input("Please enter your 10Bis email address: ")

        return email

    def collect_shufersal_orders(self):
        with ThreadPoolExecutor() as executor:
            results = executor.map(self._fetch_monthly_transactions, range(0, -self.months_back, -1))
            for monthly_transaction in results:
                self.shufersal_transactions.extend([transaction for transaction in monthly_transaction if
                                                    transaction["restaurantId"] == self.shufersal_restaurant_id])

    def _fetch_monthly_transactions(self, date_bias):
        body = {
            "culture": "he-IL",
            "uiCulture": "he",
            "dateBias": str(date_bias)
        }

        with closing(http.client.HTTPSConnection("www.10bis.co.il", context=self.context)) as conn:
            conn.request("POST", "/NextApi/UserTransactionsReport", json.dumps(body), headers=self.headers)
            res = conn.getresponse().read().decode("utf-8")
            monthly_transactions = json.loads(res)["Data"]

        return monthly_transactions["orderList"]

    def get_unused_barcodes(self):
        with ThreadPoolExecutor() as executor:
            results = [
                executor.submit(self._fetch_unused_order, transaction["orderId"])
                for transaction in self.shufersal_transactions
            ]

        for f in results:
            result = f.result()
            if result:
                if not result["url"]:
                    print(
                        "Skipping a corrupt barcode without url."
                        "barcode:\r\n", str(result)
                    )
                    continue

                self.unused_barcodes.append(result)

    def _fetch_unused_order(self, order_id):
        try:
            with closing(http.client.HTTPSConnection("api.10bis.co.il", context=self.context)) as conn:
                conn.request("GET", "/api/v1/Orders/" + str(order_id), headers=self.headers)
                res = conn.getresponse().read().decode("utf-8")
                order = json.loads(res)

                if not order["barcode"]["used"]:
                    return {
                        "url": order["barcode"]["barCodeImgUrl"],
                        "amount": order["barcode"]["amount"],
                        "validDate": order["barcode"]["validDate"],
                        "barcodeNumber": order["barcode"]["barCodeNumber"]
                    }

        except Exception as e:
            print(e)

    def download_barcodes(self):
        self.collect_shufersal_orders()
        self.get_unused_barcodes()
        original_dir = os.getcwd()

        if os.path.exists(self.output_dir):
            shutil.rmtree(self.output_dir)

        os.mkdir(self.output_dir)
        os.chdir(self.output_dir)

        with ThreadPoolExecutor() as executor:
            results = [
                executor.submit(self._download_single_barcode, barcode)
                for barcode in self.unused_barcodes
            ]

        for f in results:
            f.result()

        os.chdir(original_dir)

    def _download_single_barcode(self, barcode):
        try:
            url = barcode["url"]

            file_name = "{}_{}_{}.png".format(
                barcode["barcodeNumber"],
                barcode["validDate"].replace("/", "_"),
                barcode["amount"]
            )
            with urllib.request.urlopen(url, timeout=60, context=self.context) as url:
                with open(file_name, 'wb') as f:
                    f.write(url.read())
        except Exception as e:
            print(e)

    def summary(self):
        total_coupons_count = len(self.shufersal_transactions)
        total_coupuns_amount = sum(transaction["total"] for transaction in self.shufersal_transactions)
        unused_coupons_count = len(self.unused_barcodes)
        unused_coupons_amount = sum(int(barcode["amount"]) for barcode in self.unused_barcodes)

        summary_output = "Total shufersal coupons: {}\n".format(total_coupons_count)
        summary_output += "Total amount of coupons: {}\n".format(total_coupuns_amount)
        summary_output += "Used {} ILS\n\n".format(total_coupuns_amount - unused_coupons_amount)
        summary_output += "Unused coupons left: {}\n".format(unused_coupons_count)
        summary_output += "Unused coupons amount: {} ILS\n".format(unused_coupons_amount)

        return summary_output

    def send_email(self):
        if not self.script_args.send_email:
            return

        # Set up email data
        sender_email = ''
        receiver_email = ''
        smtp_server = 'smtp.gmail.com'
        smtp_port = 587
        smtp_password = ''

        subject = '10bis barcodes'
        message = 'Please see attached barcodes.'

        print("Sending your barcodes to: ", receiver_email)

        img_path = [self.output_dir + "/" +img for img in os.listdir(self.output_dir)]

        # Create message container
        msg = MIMEMultipart()
        msg['From'] = sender_email
        msg['To'] = receiver_email
        msg['Subject'] = subject

        # Attach message and image
        msg.attach(MIMEText(message))
        for img in img_path:
            with open(img, 'rb') as img:
                img_data = img.read()
            img_mime = MIMEImage(img_data)
            img_mime.add_header('Content-Disposition', 'attachment', filename=img.name.split("/")[1])
            msg.attach(img_mime)

        # Connect to SMTP server and send email
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(sender_email, smtp_password)
            server.sendmail(sender_email, receiver_email, msg.as_string())
        print("Mail sent successfully")


def spinner(icons, sleep=0.1):
    spinner_icons = itertools.cycle(icons)
    while True:
        if not spinner_running.is_set():
            break
        print(next(spinner_icons), end="\r")
        time.sleep(sleep)


ten_bis = Shufersal(months_back=100)
spinner_running = threading.Event()
spinner_running.set()

result = threading.Thread(target=ten_bis.download_barcodes)
spinner_thread = threading.Thread(target=spinner, kwargs={"icons": ['🍔', '🍟', '🍕', '🍩', '🍰', '🍝']})

spinner_thread.start()
result.start()

result.join()
spinner_running.clear()
spinner_thread.join()

print(ten_bis.summary())

if ten_bis.script_args.send_email:
    spinner_running.set()
    spinner_thread = threading.Thread(target=spinner, kwargs={"icons": ['📭', '📬'], "sleep": 0.2})
    spinner_thread.start()

    ten_bis.send_email()

    spinner_running.clear()
    spinner_thread.join()
