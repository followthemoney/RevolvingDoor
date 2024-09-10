from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
import html_to_json
# Setup options to connect to the remote Selenium server

def get_json():
    chrome_options = Options()
    chrome_options.add_argument('--headless')  # Optional: Run in headless mode
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')

    # Connect to the Selenium server in Docker
    driver = webdriver.Remote(
        command_executor='http://localhost:4444',
        options=chrome_options
    )

    people = []
    output_json = None
    try:
        # Example: Open a website and get the title
        driver.get("https://memberspage.cor.europa.eu/members")
        #print("Page title is:", driver.title)

        # Example: Find an element by its ID and print its text
        element = driver.find_element(By.XPATH, "/html/body/mp-root/main/mp-member-list/div/div/form/div[1]/button[3]")
        print("Element text is:", element.text)
        TITLE = element.text
        element.click()
        element = driver.find_element(By.XPATH, '//*[@id="membersList"]')
        html = element.get_attribute('innerHTML')
        output_json = html_to_json.convert(html)

    finally:
        # Close the browser and end the session
        driver.close()
        driver.quit()
    
    return output_json

def decode_json(output_json):
    peoples = []
    for el in output_json['li'][1:]:
        peoples.append(el['div'][1]['a'][0]['span'][0]['_value'].replace(',', '').lower())
    return peoples

def get_outgoing_CoR():
    output_json = get_json()
    if output_json != None: 
        return decode_json(output_json)
    else:
        print('Error with the process')
        return None