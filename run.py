#!/usr/bin/env python3
import os
import sys
import pickle
from os import listdir
from os.path import isfile, join
from time import sleep

from selenium import webdriver
from selenium.common import NoSuchElementException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from hurry.filesize import size
from urllib import parse

import config

home = 'https://www.facebook.com/'
folder = "D:\PHOTO\Домашние\АРХИВЫ\ПРИРОДА виды улица интерьеры животные\с 2007 по 2009 г"
index_file = 1
cookie_filename = f"fb.pkl"  # todo в название файла логин добавить


def init_driver():
    chrome_options = webdriver.ChromeOptions()
    chrome_options.add_experimental_option("detach", True)
    chrome_options.add_argument("--disable-infobars")
    chrome_options.add_experimental_option("prefs", {
        "profile.default_content_setting_values.notifications": 2  # 1:allow, 2:block
    })

    driver = webdriver.Chrome(options=chrome_options)#todo добавить опцию не показывать браузер

    return driver

def login(driver, usr, pwd):
    # Enter user email
    elem = driver.find_element(By.ID, "email")
    elem.send_keys(usr)
    # Enter user password
    elem = driver.find_element(By.ID, "pass")
    elem.send_keys(pwd)
    # Login
    elem.send_keys(Keys.RETURN)
    sleep(70)

def add_trusted_device(driver):
    # Если появится кпонка "Сделать устройство доверенным"
    # todo включить бесконечное ожидание, пока я вход на телефоне не подтвержу
    # todo папку задавать на входе, полный путь к ней искать самостоятельно
    body = driver.find_element(By.CSS_SELECTOR, "body")
    body.click()

    try:
        button = driver.find_element(By.XPATH, "//*[text()='Сделать это устройство доверенным']")
        button.click()
    except NoSuchElementException:
        pass

    sleep(5)

def save_cookies(driver , filename):
    pickle.dump(driver.get_cookies(), open(filename, 'wb'))
    print("cookies saved successfully")

def add_cookies(driver, filename):
    try:
        cookies = pickle.load(open(filename, 'rb'))
    except FileNotFoundError:
        return False

    if cookies:
        for cookie in cookies:
            driver.add_cookie(cookie)
        print("cookies added successfully")
        return True
    else:
        return False

def upload_to_album(driver, files: list[str], files_meta: dict):
    # Открытие созданного альбома на редактирование и догрузка в него остальных файлов
    global index_file
    current_url = driver.current_url

    query_def = parse.parse_qs(parse.urlparse(current_url).query)['set'][0]
    album_id = query_def.lstrip('a.')
    files_count = len(files_meta)

    print(f"ID только что созданного альбома: {album_id}")

    driver.get(f"{home}media/set/edit/a.{album_id}")
    sleep(5)

    # Загрузка файлов
    files_input = driver.find_element(By.XPATH, "//input[@type='file']")

    for file in files:
        ipath = '\\'.join([folder, file])
        print(f"Загрузка фото: {file} {size(files_meta[file])}")
        files_input.send_keys(ipath)
        print(f"Загружено {index_file} фото из {files_count}", flush=True)
        print(f"Загружено {index_file} фото из {files_count}", flush=True)  # todo прогресс для веса
        sys.stdout.flush()
        index_file += 1
        sleep(0.2)

    # Кнопка "Добавить в альбом"
    sleep(5)
    while True:
        add_dialogs = driver.find_elements(By.XPATH, "//*[text()='Добавить в альбом']")  # "//*[@aria-label='Добавление в альбом' and @role='dialog']"
        add_dialogs = add_dialogs[::-1]
        print(f"Открытых диалоговых окон: {len(add_dialogs)}")

        if not add_dialogs:
            break

        for index, button in enumerate(add_dialogs):
            print(f"Кнопка: {button}")
            try:
                button.click()
            except WebDriverException:
                continue

            print(f"Сохранение фото {index}")
            del add_dialogs[index]
            # После клика дождаться пока опубликуется
            sleep(5)
            break  # После отправки формы список диалоговых окон нужно получать заново, т.к. самого верхнего окна в списке больше не осталось

    sleep(5)

    submit_button = driver.find_element(By.XPATH, "//*[text()='К альбому']")
    submit_label = driver.find_element(By.XPATH, "//*[@aria-label='К альбому']")

    while True:
        sleep(1)
        try:
            if submit_label.get_attribute('aria-disabled'):
                continue

            submit_button.click()
        except WebDriverException:
            continue
        print("Отправка формы")
        break

    sleep(50)


def main():
    global index_file

    # Your Facebook account user and password
    usr = config.USER_NAME
    pwd = config.PASSWORD
    driver = init_driver()

    # Go to facebook.com
    driver.get(home)
    sleep(2)  # todo от пауз избавиться
    # todo Распознавать попап "Вы временно заблокированы"

    if not add_cookies(driver, cookie_filename):
        login(driver, usr, pwd)
        add_trusted_device(driver)
        save_cookies(driver, cookie_filename)

    #todo обрыв связи обрабатывать
    #todo очистка списка от дубликатов

    driver.get(home + "media/set/create")
    sleep(5)

    #todo пройтись по структуре папок и собрать папки на аплоад и создание альбомов
    #folder = "D:\\PHOTO\\Домашние\\АРХИВЫ\\ПРИРОДА виды улица интерьеры животные\\2012 г" #todo дозакинуть

    files = [f for f in listdir(folder) if isfile(join(folder, f))]
    files_sizes = [os.path.getsize(join(folder, f)) for f in listdir(folder) if isfile(join(folder, f))]
    files_count = len(files)
    print(f"Найдено файлов для загрузки {files_count} {size(sum(files_sizes))}")

    files_meta = dict(zip(files, files_sizes))
    files_input = driver.find_element(By.XPATH, "//input[@type='file']")

    splited_size = 100
    files_splited = [files[x:x + splited_size] for x in range(0, len(files), splited_size)]

    # Создание альбома и загрузка файлов
    files = files_splited[0]

    for file in files:
        ipath = '\\'.join([folder, file])
        print(f"Загрузка фото: {file} {size(files_meta[file])}")
        files_input.send_keys(ipath)
        print(f"Загружено {index_file} фото из {files_count}", flush=True)
        print(f"Загружено {index_file} фото из {files_count}", flush=True)#todo прогресс для веса
        sys.stdout.flush()
        index_file += 1
        sleep(0.2)

    # Ввести название альбома
    album_name = folder.split("\\")
    del album_name[0]
    del album_name[0]
    album_name = '\\'.join(album_name)
    elem = driver.find_element(By.XPATH, "//input[@type='text']")
    elem.send_keys(album_name)
    print(f"Название альбома: {album_name}")

    sleep(2)

    # Дождаться загрузки файлов и нажать кнопку создания альбома
    #todo прогресс аплоада файлов в консоль передавать
    submit_button = driver.find_element(By.XPATH, "//*[text()='Отправить']")
    submit_label = driver.find_element(By.XPATH, "//*[@aria-label='Отправить']")

    retry_count = 0
    while True:
        sleep(1)
        # проверка на ошибки загрузки отдельных файлов
        try:
            repeat_button = driver.find_element(By.XPATH, "//*[text()='Повторить попытку']")
            repeat_button.click()
            retry_count += 1
            print(f"Повторная загрузка файлов с ошибками. Попытка {retry_count}")
        except WebDriverException:
            retry_count += 1

        sleep(5)


        if retry_count >= 10:
            try:
                print("Снятие проблемных файлов с загрузки")
                delete_item_labels = driver.find_elements(By.XPATH, "//*[@aria-label='Удалить видео']")
                for label in delete_item_labels:
                    label.click()
                    sleep(1)
            except WebDriverException:
                pass
            retry_count = 0

        try:
            if submit_label.get_attribute('aria-disabled'):
                continue

            album_description = driver.find_element(By.XPATH, "//*[@aria-label='Описание (необязательно)']").find_element(By.XPATH, '//textarea')
            album_description.send_keys(album_name)

            submit_button.click()
        except WebDriverException:
            continue
        print("Отправка формы")

        break

    del files_splited[0]
    sleep(100) # todo добавить ожидание когда завершится перенаправление на страницу созданного альбома

    while True:
        if not files_splited:
            break
        upload_to_album(driver, files_splited[0], files_meta)
        del files_splited[0]

    print("Загрузка завершена")
    sleep(500)

    driver.close()


    '''
    for group in grp:
    
        driver.get(group)
    
        try:
    
            try:
    
                commentr = WebDriverWait(driver,10).until(EC.element_to_be_clickable( (By.XPATH, "//*[@name='xhpc_message_text']") ))
                commentr.click()
    
            except Exception:
                commentr = WebDriverWait(driver,10).until(EC.element_to_be_clickable( (By.XPATH, "//*[@loggingname='status_tab_selector']") ))
                commentr.click()
    
    
    
            commentr = WebDriverWait(driver,10).until(EC.element_to_be_clickable( (By.XPATH, "//*[@class='_3u15']") ))
            commentr.click()
    
            sleep(3)
            l=driver.find_elements_by_tag_name('input')
            sleep(1)
    
            for g in l:
                if g==driver.find_element_by_xpath("//input[@type='file'][@class='_n _5f0v']"):
                    sleep(1)
                    g.send_keys(ipath)
                    print('image loaded')
    
    
    
    
            sleep(10)
            driver.find_element_by_xpath("//*[@class='_1mf _1mj']").send_keys(message)
    
            sleep(1)
            buttons = driver.find_elements_by_tag_name("button")
            sleep(1)
            for button in buttons:
                    if button.text == "Post":
                        sleep(5)
                        button.click()
                        sleep(10)
    
        except Exception:
            pass
            print ('image not posted in '+group)
    '''



if __name__ == '__main__':
    main()
