import base64
import datetime
import glob
import io
import json
import logging
import math
import os
import tempfile

import azure.functions as func
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
from azure.storage.blob import BlobClient, BlobServiceClient


def main(req: func.HttpRequest) -> func.HttpResponse:
    # debugging start the function
    logging.info("------------------------------------------------")
    logging.info(f"{json.dumps((payload := req.get_json()[0]), indent=4)}")
    logging.info("------------------------------------------------")

    # preparing variables
    subscription_name, starting_date = (data := payload["data"]["url"].split("/")[-1])[
        :-11
    ], data[-10:-4]
    azure_bill_table_container_name, azure_bill_container_name = (
        "azurebilltable",
        "azurebill",
    )
    price, current_month_df, previous_month_df = [np.float64(0)] * 6, None, None
    billing_periods = sorted(
        (
            temp_date := str(
                datetime.datetime.strptime(f"{starting_date}03", "%Y%m%d")
                - datetime.timedelta(days=i * 30)
            ).split("-")
        )[0]
        + temp_date[1]
        for i in range(6)
    )
    logging.info(billing_periods)
    with tempfile.TemporaryDirectory() as tempdir_path:
        # os.chdir(tempdir_path)
        for billing_period in billing_periods:
            try:
                blob = BlobClient.from_connection_string(
                    conn_str=os.environ["AZBILL_STORAGE_ACCOUNT_CONNECTION_STRING"],
                    container_name=azure_bill_container_name,
                    blob_name=(
                        blob_name := f"{subscription_name}_{billing_period}.csv"
                    ),
                )
                download_path = os.path.join(tempdir_path, blob_name)
                with open(download_path, "wb") as my_blob:
                    blob_data = blob.download_blob()
                    blob_data.readinto(my_blob)
                    df = pd.read_csv(
                        io.StringIO(attachment := blob_data.content_as_text()), sep=","
                    )
                    price.append(round(df["Cost"].sum(), 2))
                    price.remove(np.float64(0))
                    if billing_period == billing_periods[-1]:
                        current_month_df = df
                    if billing_period == billing_periods[-2]:
                        previous_month_df = df
            except Exception as e:
                logging.info(f"{e}")

    # styling plt
    plt.style.use("bmh")

    # constructing bar chart
    plt.figure(figsize=(15, 5))
    ax = plt.subplot(1, 2, 1)
    bars = ax.bar(billing_periods, price, color="green", alpha=0.7, label="AUD $")
    for bar in bars:
        height = bar.get_height()
        ax.annotate(
            "${0}".format(height),
            xy=(bar.get_x() + bar.get_width() / 2, height),
            xytext=(0, 3),
            textcoords="offset points",
            ha="center",
            va="bottom",
        )
    plt.title("Azure Monthly Subscription Cost for " + subscription_name)
    plt.xlabel("Month")
    plt.xticks(rotation="0")
    plt.ylabel("AUD $")
    plt.legend(loc="lower right")
    plt.tight_layout()
    with tempfile.TemporaryDirectory() as tempdir_path:
        # os.chdir(tempdir_path)
        bar_graph_path = os.path.join(
            tempdir_path, f"{subscription_name}_bar_graph.jpg"
        )
        plt.savefig(bar_graph_path)
        logging.info(glob.glob(f"{tempdir_path}/*"))
        with open(bar_graph_path, "rb") as file_reader:
            message_bytes = file_reader.read()
            base64_bytes = base64.b64encode(message_bytes)
            bar_graph_base64_message = base64_bytes.decode("ascii")

    # constructing horizontal bar chart
    plt.figure(figsize=(15, 5))
    ax = plt.subplot(1, 2, 1)
    ax.barh(
        (cost_df := current_month_df.groupby("ServiceName").sum()).index,
        cost_df["Cost"],
        alpha=0.5,
        label="Current Month",
    )
    if isinstance(previous_month_df, pd.DataFrame):
        ax.barh(
            (cost_df := previous_month_df.groupby("ServiceName").sum()).index,
            cost_df["Cost"],
            alpha=0.5,
            label="Previous Month",
        )
    plt.title("Azure Resource Cost Breakdown for " + blob_name[:-4])
    plt.xlabel("AUD $")
    plt.xticks(rotation="0")
    plt.ylabel("Service Name")
    plt.legend(loc="lower right")
    plt.tight_layout()
    with tempfile.TemporaryDirectory() as tempdir_path:
        # os.chdir(tempdir_path)
        barh_graph_path = os.path.join(
            tempdir_path, f"{subscription_name}_barh_graph.jpg"
        )
        plt.savefig(barh_graph_path)
        logging.info(glob.glob(f"{tempdir_path}/*"))
        with open(barh_graph_path, "rb") as file_reader:
            message_bytes = file_reader.read()
            base64_bytes = base64.b64encode(message_bytes)
            barh_graph_base64_message = base64_bytes.decode("ascii")

    # constructing pie chart
    plt.figure(figsize=(17, 10))
    ax = plt.subplot(1, 2, 1)
    cost_df = df.groupby("ServiceName").sum()
    pie = ax.pie(
        cost_df["Cost"], labeldistance=0.5, shadow=False, startangle=0, radius=1.1
    )
    for label, t in zip(cost_df.index, pie[1]):
        x, y = t.get_position()
        angle, ha, va = int(math.degrees(math.atan2(y, x))), "left", "bottom"
        if angle > 90 or -180 <= angle <= -90:
            angle -= 180
        if angle < 0:
            va = "top"
        if -45 <= angle <= 0:
            ha, va = "right", "bottom"
        plt.annotate(label, xy=(x, y), rotation=angle, ha=ha, va=va, size=7)
    plt.title("Azure Resource Cost Breakdown for " + blob_name[:-4])
    plt.legend(loc="lower left", labels=cost_df.index)
    plt.tight_layout()
    with tempfile.TemporaryDirectory() as tempdir:
        # os.chdir(tempdir_path)
        pie_graph_path = os.path.join(tempdir, f"{subscription_name}_pie_graph.jpg")
        plt.savefig(pie_graph_path)
        logging.info(glob.glob(f"{tempdir_path}/*"))
        with open(pie_graph_path, "rb") as file_reader:
            message_bytes = file_reader.read()
            base64_bytes = base64.b64encode(message_bytes)
            pie_graph_base64_message = base64_bytes.decode("ascii")

    # reading azure bill table
    try:
        blob_service_client = BlobServiceClient.from_connection_string(
            os.environ["AZBILL_STORAGE_ACCOUNT_CONNECTION_STRING"]
        )
        blob_client = blob_service_client.get_blob_client(
            azure_bill_table_container_name, "azurebilltable.csv"
        )
        azure_bill_table = {
            (col := row.split(","))[0]: [
                float(col[1]),
                col[2],
                col[3],
                col[4],
                col[5],
                col[6],
                col[7],
            ]
            for row in blob_client.download_blob()
            .content_as_text(encoding="UTF-8")
            .splitlines()[1:]
        }
        logging.info(json.dumps(azure_bill_table, indent=4))
        logging.info(subscription_name)
        logging.info(azure_bill_table[subscription_name])
    except Exception as e:
        logging.info(f"{e}")

    # sending payload to logicapp
    try:
        logging.info(
            requests.post(
                url=os.environ["LOGIC_APP_URL"],
                json={
                    "blob_name": blob_name,
                    "bar_graph_image": bar_graph_base64_message,
                    "barh_graph_image": barh_graph_base64_message,
                    "pie_graph_image": pie_graph_base64_message,
                    "attachment": attachment,
                    "subscription_name": subscription_name,
                    "rate": "Passthrough (Customer Self-Managed)"
                    if azure_bill_table[subscription_name][0] == 1.0
                    and azure_bill_table[subscription_name][1] != "Cenitex"
                    else "Passthrough (Cenitex Owned)"
                    if azure_bill_table[subscription_name][0] == 1.0
                    and azure_bill_table[subscription_name][1] == "Cenitex"
                    else "25% (Cenitex Managed)"
                    if azure_bill_table[subscription_name][0] == 1.25
                    else "43.75% (Viccloudsafe Kofax)",
                    "department": azure_bill_table[subscription_name][1],
                    "contact": azure_bill_table[subscription_name][2],
                    "application": azure_bill_table[subscription_name][3],
                    "project_code": azure_bill_table[subscription_name][4],
                    "project_manager": azure_bill_table[subscription_name][5],
                    "business_unit": azure_bill_table[subscription_name][6],
                    "price_difference": f"Please note the cost difference from the previous month by ${difference if (difference := round(price[-1] - price[-2], 2)) > 0 else abs(difference)}.",
                },
            )
        )
    except requests.exceptions.RequestException as e:
        raise SystemExit(e)

    # return http
    return func.HttpResponse(status_code=200)
