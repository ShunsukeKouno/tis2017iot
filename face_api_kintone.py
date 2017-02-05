
#-*- coding: utf-8 -*-

"""
ラズパイに接続された人感センサから人を検知し、検出された場合は写真を撮影して
検出された人の年齢と性別を推定してKintoneにデータを送信するサンプルプログラムです。

使用デバイス：ラズパイ３、ラズパイカメラ、人感センサ（M-09627）
外部サービス：Microsoft Face API（写真から人検出）
　　　　　　　Kintone API（推定結果の保存・ビジュアライズ）

準備：
   1. MS Face APIキーの取得
   2. Kintoneアプリの作成（アプリのドメイン、IDの設定とトークンの取得）
　 3. config/配下にms_api_key.yaml とkintone_conf.yamlを新規作成し、上記情報を書き込む

"""

import urllib
import os
import sys
import smbus
import subprocess
import json
from datetime import datetime
import requests
import yaml
from time import sleep
import RPi.GPIO as GPIO

PIN = 4
GPIO.setmode(GPIO.BCM)
GPIO.setup(PIN, GPIO.IN)

bus = smbus.SMBus(1)
address_tmp = 0x48
register_tmp = 0x00


BASE_DIR = os.path.dirname(__file__)

# ファイルからMS APIキーとKintone設定ファイルのの読み込み
ms_api_key = yaml.load(open(os.path.join(BASE_DIR, 'conf/ms_api_key.yaml')).read())
#kintone_conf = yaml.load(open(os.path.join(BASE_DIR, 'conf/kintone_conf.yaml')).read())

# MS Face APIのヘッダ
face_api_headers = {
    'Content-Type': 'application/octet-stream',
    'Ocp-Apim-Subscription-Key': ms_api_key['key'],
}

# Kintone APIのヘッダ
#kintone_api_headers = {
#    'Content-Type': 'application/json',
#    'X-Cybozu-API-Token': kintone_conf['token'],
#}

# MS Face APIのパラメータ
# 参考：https://dev.projectoxford.ai/docs/services/563879b61984550e40cbbe8d/operations/563879b61984550f30395236
face_api_params = urllib.parse.urlencode({
    'returnFaceId': 'false',
    'returnFaceLandmarks': 'false',
    'returnFaceAttributes': 'age,gender',
})
def read_tmp_sensor():
    word_data =  bus.read_word_data(address_tmp, register_tmp)
    data = (word_data & 0xff00)>>8 | (word_data & 0xff)<<8
    data = data>>4 # 12ビットデータ
    if data & 0x800 == 0:  # 温度が正の場合
        temperature = data*0.0625
    else: # 温度が負の場合、絶対値を取ってからマイナスをかける
        temperature = ( (~data&0xfff) + 1)*-0.0625
    return temperature

# rest interface setting
key = os.getenv("maker_key")
event = os.getenv("maker_event_store_sensor")
trigger_url = 'https://maker.ifttt.com/trigger/' + event + '/with/key/' + key
def send_face_attr_to_kintone(face_results):
    """
    検出されたすべての顔データをKintoneにPOSTする
    """

    # 顔の検出人数分だけループ
    for result in face_results:
        # 性別と年齢のみ取り出す
        gender = result['faceAttributes']['gender']
        age = result['faceAttributes']['age']
        temp = read_tmp_sensor()

        payload = {'value1':gender,'value2':age,'value3':temp}
        r = requests.post(trigger_url, data=payload)
        print( "success" if r.status_code == 200 else "fail")

        record = {"datetime": {'value': datetime.now().strftime('%Y-%m-%dT%H:%M:%S+09:00')}, "age": {'value': age}, "gender": {'value': gender}}
        # 1人分をKintoneへPOST
        response = requests.post('https://{}.cybozu.com/k/v1/record.json'.format(kintone_conf['domain']), data=json.dumps(payload), headers=kintone_api_headers)

        if response.ok:
            pass
        else:
            print('Error!')
            print(response.raise_for_status())
def send_ifttt(face_results):
    # 顔の検出人数分だけループ
    for result in face_results:
        # 性別と年齢のみ取り出す
        gender = result['faceAttributes']['gender']
        age = result['faceAttributes']['age']
        #temp = read_tmp_sensor()

        payload = {'value1':gender,'value2':age,'value3':1}
        r = requests.post(trigger_url, data=payload)
        print( "success" if r.status_code == 200 else "fail")

        #record = {"datetime": {'value': datetime.now().strftime('%Y-%m-%dT%H:%M:%S+09:00')}, "age": {'value': age}, "gender": {'value': gender}}

def detect_faces(filename):
    """
    Microsoft Face APIで画像から顔を検出する
    """

    face_image = open(filename, "r+b").read()

    # Miscosoft Face APIへ画像ファイルをPOST
    response = requests.post('https://westus.api.cognitive.microsoft.com/face/v1.0/detect?%s' % face_api_params, data=face_image, headers=face_api_headers)
    results = response.json()

    if response.ok:
        print('Result-->  {}'.format(results))
    else:
        print(response.raise_for_status())
    return results

def shutter_camera():
    """
    ラズパイカメラで撮影する
    """

    # cam.jpgというファイル名、640x480のサイズ、待ち時間5秒で撮影する
    cmd = "raspistill -o cam.jpg -h 640 -w 480 -t 5000"
    subprocess.call(cmd, shell=True)

try:
    while True:
        # 人間センサからデータを読みこむ（0: 検出なし, 1:検出あり）
        human_exists = int(GPIO.input(PIN) == GPIO.HIGH)

        if human_exists:
            print('Human exists!')

            print('Taking a picture in 5 seconds...')
            shutter_camera()
            print('Done.')

            # MS Face APIで顔検出
            print('Sending the image to MS face API...')
            results = detect_faces('cam.jpg')
            send_ifttt(results)
            print('Done.')

            #if len(results) > 0:
                # Kintoneに送信
             #   print('Sending face attributes to Kintone...')
             #   send_face_attr_to_kintone(results)
             #   print('Done.')
            #else:
             #   print('No faces detected')
        else:
            print('No human')

        print('Wait 10 seconds...')
        print('------------------')
        sleep(10)

except KeyboardInterrupt:
    pass
except Exception as e:
    print(e)

GPIO.cleanup()

