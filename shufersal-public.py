# HOW TO USE:
# Open 10bis and the developers console.
# Click on Network and look for the GetUser request (or any other fetch/xhr request).
# Look for the header "user-token" and paste the value at line 135 instead of the placeholder
#
#email setup:
# change sender_email and receiver_email to the email you want it sent from and received in
#  Update the smtp:
#         fields smtp_server = 'smtp.example.com' - for gmail mail change example to gmail
#         smtp_port = 587 - depends on provider (587 is gmail)
#         smtp_username = 'your_username' - your email that is the sender
#         smtp_password = 'your_password' - use app passwords ( gmail example https://support.google.com/mail/answer/185833?hl=en)
#
# Enjoy.

import threading
import time
import http.client
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


class Shufersal:
    def __init__(self, token, months_back=12):
        self.unused_barcodes = []
        self.output_dir = "barcodes"
        self.months_back = months_back
        self.shufersal_transactions = []
        self.shufersal_restaurant_id = 26698
        self.headers = {
            "user-token": token,
            'Content-Type': 'application/json'
        }

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

        with closing(http.client.HTTPSConnection("www.10bis.co.il")) as conn:
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
                self.unused_barcodes.append(result)

    def _fetch_unused_order(self, order_id):
        with closing(http.client.HTTPSConnection("api.10bis.co.il")) as conn:
            conn.request("GET", "/api/v1/Orders/" + str(order_id), headers=self.headers)
            res = conn.getresponse().read().decode("utf-8")
            order = json.loads(res)

        if not order["barcode"]["used"] and order["orderStatus"] != "Canceled":
            return {
                "url": order["barcode"]["barCodeImgUrl"],
                "amount": order["barcode"]["amount"],
                "validDate": order["barcode"]["validDate"],
                "barcodeNumber": order["barcode"]["barCodeNumber"]
            }

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
                executor.submit(Shufersal._download_single_barcode, barcode)
                for barcode in self.unused_barcodes
            ]

        for f in results:
            f.result()

        os.chdir(original_dir)

    @staticmethod
    def _download_single_barcode(barcode):
        url = barcode["url"]
        file_name = "{}_{}_{}.png".format(
            barcode["barcodeNumber"],
            barcode["validDate"].replace("/", "_"),
            barcode["amount"]
        )
        with urllib.request.urlopen(url, timeout=60) as url:
            with open(file_name, 'wb') as f:
                f.write(url.read())

    def summary(self):
        total_coupons_count = len(self.shufersal_transactions)
        total_coupuns_amount = sum(transaction["total"] for transaction in self.shufersal_transactions)
        unused_coupons_count = len(self.unused_barcodes)
        unused_coupons_amount = sum(int(barcode["amount"]) for barcode in self.unused_barcodes)

        print("Total shufersal coupons: {}".format(total_coupons_count))
        print("Total amount of coupons: {}".format(total_coupuns_amount))
        print("Used {} ILS".format(total_coupuns_amount-unused_coupons_amount))
        print()
        print("Unused coupons left: {}".format(unused_coupons_count))
        print("Unused coupons amount: {} ILS".format(unused_coupons_amount))

    def send_email(self):
        # Set up email data
        sender_email = 'your_email@example.com'
        receiver_email = 'recipient_email@example.com'
        subject = '10bis barcodes'
        message = 'Please see attached barcodes.'

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
            img_mime.add_header('Content-Disposition', 'attachment', filename='image.jpg')
            msg.attach(img_mime)

        # Connect to SMTP server and send email
        smtp_server = 'smtp.example.com'
        smtp_port = 587
        smtp_username = 'your_username'
        smtp_password = 'your_password'
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(smtp_username, smtp_password)
            server.sendmail(sender_email, receiver_email, msg.as_string())

def spinner():
    spinner_icons = itertools.cycle(['🍔', '🍟', '🍕', '🍩', '🍰', '🍝'])
    while True:
        if not spinner_running.is_set():
            break
        print(next(spinner_icons), end="\r")
        time.sleep(0.1)











ten_bis = Shufersal(token="cvngqu7t225Sp7ZnQKi5sQ==", months_back=100)
spinner_running = threading.Event()
spinner_running.set()

result = threading.Thread(target=ten_bis.download_barcodes)
spinner_thread = threading.Thread(target=spinner)

spinner_thread.start()
result.start()

result.join()
spinner_running.clear()
spinner_thread.join()

ten_bis.summary()
ten_bis.send_email()
