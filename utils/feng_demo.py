import requests
import json

#天气：'https://your-api-host/v7/weather/3d?location=116.41%2C39.92'
#获取城市ID：'https://your-api-host/geo/v2/city/lookup?location=116.41%2C39.92'
api_host='ht64222fr2.re.qweatherapi.com'
api_key = '{YOU_API_KEY}'

def get_city_id(city_name):
    url = f'https://{api_host}/geo/v2/city/lookup?location={city_name}'
    headers = {
        'X-QW-Api-Key': api_key
    }
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        print(json.dumps(response.json(), indent=4, ensure_ascii=False))
        print(response.json()['location'][0]['id'])
        return response.json()['location'][0]['id']
    else :
        print('解析失败')
        return ''


def get_weather(location_id):
    url= f'https://{api_host}/v7/weather/3d?location={location_id}'
    headers = {
        'X-QW-Api-Key':api_key
    }
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        print(json.dumps(response.json(),indent=4,ensure_ascii=False))

if __name__=='__main__':
    location_id = get_city_id('广州')
    weather = get_weather(location_id)