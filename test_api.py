import requests

url = "https://eportal.incometax.gov.in/iec/servicesapi/getEntity"
data = {
    "aadhaarNumber": "690088871997",
    "pan": "HRSPM5185A",
    "preLoginFlag": "Y",
    "serviceName": "linkAadhaarPreLoginService"
}
try:
    resp = requests.post(url, json=data, timeout=30)
    print("Status code:", resp.status_code)
    print("Response:", resp.text)
except Exception as e:
    print("Error:", e)