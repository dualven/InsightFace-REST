import os
import json
import base64
import requests

def file2base64(path):
    with open(path, mode='rb') as fl:
        encoded = base64.b64encode(fl.read()).decode('ascii')
        return encoded


def extract_vecs(ims,max_size=640):
    target = [file2base64("test_images/" + im) for im in ims]
    req = {"images": {"data": target},"max_size":max_size}
    resp = requests.post('http://localhost:18080/extract', json=req)
    data = resp.json()
    return data
    
images_path = 'test_images'
images = os.listdir(images_path)
print(images)
data = extract_vecs(images, 640)
print(data)
