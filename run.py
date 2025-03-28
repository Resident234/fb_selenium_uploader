#!/usr/bin/env python3
from __future__ import annotations

import argparse
import inspect
import os
import pickle
import re
import sys
import threading
import time
from datetime import datetime
from functools import wraps
from os import listdir
from os.path import isfile, isdir, join
from pathlib import Path
from time import sleep
from typing import Any
from urllib import parse
import hashlib
import filetype
import requests
from hurry.filesize import size
from selenium import webdriver
from selenium.common import NoSuchElementException, WebDriverException, TimeoutException, InvalidCookieDomainException
from selenium.webdriver.chrome.webdriver import WebDriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
import speech_recognition as sr
from pydub import AudioSegment
from threading import Thread


import config

#todo для работы с глобальными переменными нужен другой способ
home: str = 'https://www.facebook.com/'
folder = ""
index_file = 1#todo в конфиг поубирать
index_to_album = 0
count_all_files = 0
size_to_album = 0
size_all_files = 0
cookie_filename = "fb.pkl"
progress_filename = f"progress.pkl"
profile_id = 0
profile_name = 'Сергей Гладышев'
album_name = ""
album_id = None

splited_size = 20
renew_cookie = False
root_folder = ''
is_headless = False
check_duplicates = False
recursive = False
connection_status = True

threadLocal = threading.local()

def print_function_name(func):#todo еще данные с параметров тоже выводить
    @wraps(func)
    def wrapper(*args, **kwargs):
        function_name = func.__name__.replace("_", " ").capitalize()
        print(function_name)  # Print function name
        return func(*args, **kwargs)
    return wrapper

@print_function_name
def get_driver() -> WebDriver:
    driver = getattr(threadLocal, 'driver', None)
    if driver is None:
        chrome_options = webdriver.ChromeOptions()
        chrome_options.add_experimental_option("detach", True)
        chrome_options.add_argument("--disable-infobars")
        chrome_options.add_experimental_option("prefs", {
            "profile.default_content_setting_values.notifications": 2  # 1:allow, 2:block
        })
        if is_headless:
            chrome_options.add_argument("--headless")

        driver = webdriver.Chrome(options=chrome_options)
        setattr(threadLocal, 'driver', driver)

    return driver


#todo попап медиафайл успешно добавлен скрывать, возможно он мешает по кнопке перехода к альбому кликать
#todo индикаторы загрузки  из интерфейса транслировать в консоль
#todo при закидывании файлов дождаться пока все окна появятся

@print_function_name
def login(driver: WebDriver, usr, pwd):
    # Enter user email
    elem = driver.find_element(By.NAME, "email")
    elem.send_keys(usr)
    # Enter user password
    elem = driver.find_element(By.NAME, "pass")
    elem.send_keys(pwd)
    # Login
    elem.send_keys(Keys.RETURN)

#todo если открытых диалоговых окон 0, то повторный поиск диалоговых окон
#todo мы удалили публикацию распознавать на всех страницах

@print_function_name
def solve_captcha(driver):
    """
    Распознавать страницу запроса капчу и ждать ввода
    :param driver:
    """
    captcha_text = solve_audio_captcha(driver)

    print("Текст капчи:" + captcha_text)
    input = driver.find_element(By.XPATH, "//input[@type='text']")
    input.send_keys(captcha_text)
    sleep(1)
    submit_button = driver.find_element(By.XPATH, "//*[text()='Продолжить']")
    submit_button.click()

    #todo инструкцию по развертыванию написать и первый ответ тоже https://stackoverflow.com/questions/55669182/how-to-fix-filenotfounderror-winerror-2-the-system-cannot-find-the-file-speci
    #todo мониторить сообщение "Не удалось добавить медиафайлы в этот альбом". Релоадить страницу и начинать загрузку фото заново. Засекать проблемный файл и выкидывать его из списка
    #todo в консоль записывать имена файлов, которые сохраняются
    
    try:
        WebDriverWait(driver, 1000).until(EC.invisibility_of_element_located((By.XPATH, "//*[text()='Введите символы, которые вы видите']")))
    except WebDriverException:
        pass

@print_function_name
def solve_audio_captcha(driver):
    audio_src = driver.find_element(By.XPATH, "//*[text()='воспроизвести аудио']").get_attribute('href')
    driver.execute_script("window.open('');")
    # Switch to the new window
    driver.switch_to.window(driver.window_handles[1])
    driver.get(audio_src)

    sleep(10)  # todo дождаться пока загрузится

    audio_element = driver.find_element(By.CSS_SELECTOR, "audio")
    audio_url = audio_element.get_attribute('src')
    response = requests.get(audio_url)
    if response.status_code == 200:
        with open(r"C:\Users\Professional\audio.mp3",
                  'wb') as f:  # @todo имена и расположение файлов а так же их очистка
            f.write(response.content)

    driver.switch_to.window(driver.window_handles[0])

    # convert mp3 file to wav
    src = r"C:\Users\Professional\audio.mp3"
    sound = AudioSegment.from_mp3(src)
    sound.export(r"C:\Users\Professional\audio.wav", format="wav")

    file_audio = sr.AudioFile(r"C:\Users\Professional\audio.wav")  # todo путь поправить

    # use the audio file as the audio source
    r = sr.Recognizer()
    with file_audio as source:
        audio_text = r.record(source)

    captcha_text = r.recognize_google(audio_text)
    captcha_text = captcha_text.replace(" ", "")

    return captcha_text

@print_function_name
def check_page(driver: WebDriver, page: str) -> str | bool:
    match page:
        case 'captcha': # страница запроса капчи
            try:
                WebDriverWait(driver, 3).until(EC.presence_of_element_located((By.XPATH, "//*[text()='Введите символы, которые вы видите']")))
            except WebDriverException:
                return False
            return True

        case 'index':
            try:
                WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.XPATH, "//*[@aria-label='Ваш профиль']")))
            except WebDriverException as e:
                return False
            return True

        case 'login':
            try:
                WebDriverWait(driver, 3).until(EC.presence_of_element_located((By.XPATH, "//*[text()='Недавние входы']"))) # or
            except WebDriverException:
                return False
            return True

        case 'two_step_verification':
            try:
                WebDriverWait(driver, 3).until(EC.presence_of_element_located((By.XPATH, "//*[text()='Проверьте уведомления на другом устройстве' or text()='Проверьте сообщения WhatsApp']")))
            except WebDriverException:
                return False
            return True

        case 'add_trusted_device':
            try:
                WebDriverWait(driver, 3).until(EC.presence_of_element_located((By.XPATH, "//*[text()='Проверьте уведомления на другом устройстве']")))
            except WebDriverException:
                return False
            return True

        case _:
            return False

#todo для паузы доработать форматированный вывод оставшегося времени, часы тоже выводить

@print_function_name
def two_step_verification_wait(driver):
    """
    бесконечное ожидание, пока я вход на телефоне не подтвержу
    :param driver:
    """
    title = driver.find_element(By.XPATH, "//*[text()='Проверьте уведомления на другом устройстве' or text()='Проверьте сообщения WhatsApp']")
    inp = Inp(f'{title.text} и введите код: ').get()
    if inp:
        print(f'Ввод принят: {inp}')
        elem = driver.find_element(By.XPATH, "//input[@type='text']")
        elem.send_keys(inp)
        sleep(1)
        submit_button = driver.find_element(By.XPATH, "//*[text()='Продолжить']")
        submit_button.click()
    try:
        WebDriverWait(driver, 1000).until(EC.invisibility_of_element_located((By.XPATH, "//*[text()='Проверьте уведомления на другом устройстве' or text()='Проверьте сообщения WhatsApp']")))
    except WebDriverException:
        driver.close()
        sys.exit('Код из уведомления не был введен')

@print_function_name
def add_trusted_device(driver):
    """
    Если появится кпонка "Сделать устройство доверенным"
    :param driver:
    """
    try:
        button = WebDriverWait(driver, 1).until(EC.presence_of_element_located((By.XPATH, "//*[text()='Сделать это устройство доверенным']")))
        button.click()
    except NoSuchElementException:
        pass

@print_function_name
def save_cookies(driver: WebDriver, filename):
    pickle.dump(driver.get_cookies(), open(filename, 'wb'))
    print("cookies saved successfully")

@print_function_name
def add_cookies(driver: WebDriver, filename):
    try:
        cookies = pickle.load(open(filename, 'rb'))
    except FileNotFoundError:
        return False

    if cookies:
        try:
            now_timestamp = datetime.timestamp(datetime.now())
            #[{'domain': '.facebook.com', 'expiry': 1735714471, 'httpOnly': True, 'name': 'fr', 'path': '/', 'sameSite': 'None', 'secure': True, 'value': '05ph6f0hw4tuSzo9F.AWU-O3D10vsFCE9voUFq_NNXPMQ.Bm_j9b..AAA.0.0.Bm_j-m.AWU8cqDJJyc'}, {'domain': '.facebook.com', 'expiry': 1759474424, 'httpOnly': True, 'name': 'xs', 'path': '/', 'sameSite': 'None', 'secure': True, 'value': '35%3A0UNfy0QwpAuLmw%3A2%3A1727938422%3A-1%3A14476'}, {'domain': '.facebook.com', 'expiry': 1759474424, 'httpOnly': False, 'name': 'c_user', 'path': '/', 'sameSite': 'None', 'secure': True, 'value': '100007859116486'}, {'domain': '.facebook.com', 'expiry': 1728543205, 'httpOnly': False, 'name': 'locale', 'path': '/', 'sameSite': 'None', 'secure': True, 'value': 'ru_RU'}, {'domain': '.facebook.com', 'httpOnly': False, 'name': 'presence', 'path': '/', 'sameSite': 'Lax', 'secure': True, 'value': 'C%7B%22t3%22%3A%5B%5D%2C%22utc3%22%3A1727938473890%2C%22v%22%3A1%7D'}, {'domain': '.facebook.com', 'expiry': 1728543273, 'httpOnly': False, 'name': 'wd', 'path': '/', 'sameSite': 'Lax', 'secure': True, 'value': '929x873'}, {'domain': '.facebook.com', 'expiry': 1762498397, 'httpOnly': True, 'name': 'datr', 'path': '/', 'sameSite': 'None', 'secure': True, 'value': 'Wz_-ZubvX8PhEuJo2hFYXuKA'}, {'domain': '.facebook.com', 'expiry': 1762498424, 'httpOnly': True, 'name': 'sb', 'path': '/', 'sameSite': 'None', 'secure': True, 'value': 'Wz_-ZluV4_krp6As8GZW3_l_'}]
            for cookie in cookies:
                if cookie.get('expiry') and cookie['expiry'] < now_timestamp:
                    print("cookies expired")
                    return False
                driver.add_cookie(cookie)
        except InvalidCookieDomainException:
            return False

        print("cookies added successfully")
        return True
    else:
        return False

@print_function_name
def save_progress(album_id, file_number, album_name):
    pickle.dump([album_id, file_number, album_name], open(progress_filename, 'wb'))

@print_function_name
def clear_saved_progress():
    if os.path.isfile(progress_filename):
        os.remove(progress_filename)
    print(f"Сохраненный прогресс {progress_filename} очищен")

@print_function_name
def restore_progress() -> bool | tuple[Any]:
    try:
        progress = pickle.load(open(progress_filename, 'rb'))
    except FileNotFoundError:
        return False

    return *progress,


# todo подумать как отрефакторить эти циклы и оптимизировать
# todo все всплывающие уведомления транслировать в консоль
# todo доработать ошибку таймаута в случае обрыва соединения
# todo вести статистику ошибок сохранения конкретных файлов и перезапускать сохранение, исключив проблемные файлы из списка

@print_function_name
def sleep_throttling(attempt):
    """
    Function to implement an Exponential Backoff throttling mechanism based on the given attempt number.
    The delay between retries increases exponentially with the number of attempts,
    allowing controlled retries and avoiding excessive immediate retries. During
    the delay period, a countdown is displayed with progress feedback.

    :param attempt: The current attempt number, starting from 0, that determines
                    the delay duration. The delay is calculated as 2 ** attempt.
    :type attempt: int
    :return: None
    """
    delay = 2 ** attempt
    for i in range(delay, 0, -1):
        sys.stdout.write(str(i) + ' ')
        sys.stdout.flush()
        minutes, seconds = divmod(i, 60)
        print_progress_bar(i, delay, prefix='sleep:', suffix=f"Осталось{' ' + str(minutes) + ' минут и' if minutes > 0 else ''} {seconds} секунд", length=50)
        time.sleep(1)

@print_function_name
def get_add_dialogs(driver):
    add_dialogs = driver.find_elements(By.XPATH, "//*[text()='Добавить в альбом']")  # "//*[@aria-label='Добавление в альбом' and @role='dialog']"
    return add_dialogs[::-1]

@print_function_name
def upload_to_album(driver: WebDriver, album_id: int, files: list[str]):
    # Открытие созданного альбома на редактирование и догрузка в него остальных файлов
    global index_file, index_to_album, size_to_album

    print(f"ID альбома: {album_id}")

    check_connection(driver)
    driver.get(f"{home}media/set/edit/a.{album_id}")
    add_dialogs = None
    problems_count = 0

    while True:
        check_connection(driver)
        popup_text = check_popups(driver)
        if popup_text:
            print(f"Обнаружен попап {popup_text}")
            print_progress_bar(size_to_album, size_all_files, prefix='Текущий прогресс:', suffix='Complete', length=50)
            problems_count += 1
            sleep_throttling(problems_count)
            print(f"Ошибок загрузки файлов: {problems_count}")
            continue


        print("Загрузка файлов")
        files_input = WebDriverWait(driver, 1000).until(EC.presence_of_element_located((By.XPATH, "//input[@type='file']")))
        set_files_to_field(files_input, files)

        # Кнопка "Добавить в альбом"
        WebDriverWait(driver, 300).until(EC.presence_of_element_located((By.XPATH, "//*[text()='Добавление в альбом']")))

        prev_dialogs_count = 0
        problems_count = 0
        while True:
            check_connection(driver)
            try:     
                popup_text = check_popups(driver)
                if popup_text:
                    print(f"Обнаружен попап {popup_text}")
                    print_progress_bar(size_to_album, size_all_files, prefix='Текущий прогресс:', suffix='Complete', length=50)
                    problems_count += 1
                    sleep_throttling(problems_count)
                    print(f"Ошибок добавления: {problems_count}")

                add_dialogs = get_add_dialogs(driver)
                dialogs_count = len(add_dialogs)
                print(f"Открытых диалоговых окон: {dialogs_count}")

                if prev_dialogs_count != 0 and prev_dialogs_count == dialogs_count:
                    print_progress_bar(size_to_album, size_all_files, prefix='Текущий прогресс:', suffix='Complete', length=50)
                    problems_count += 1
                    sleep_throttling(problems_count)
                    print(f"Ошибок добавления: {problems_count}")

                if problems_count >= 100:
                    print(f"Ошибка добавления {problems_count}. Обновление страницы")
                    driver.refresh()
                    break

                prev_dialogs_count = dialogs_count

                if not add_dialogs:
                    break

                for index, button in enumerate(add_dialogs):
                    check_connection(driver)
                    try:
                        button_container = button.find_element(By.XPATH, ".//ancestor::div[@aria-label=\"Добавить в альбом\"]")
                        WebDriverWait(driver, 500).until(lambda x: button_container.get_attribute("aria-disabled") != "true" or button_container.get_attribute("aria-disabled") is None)
                        button.click()
                    except WebDriverException:
                        continue

                    print(f"Сохранение фото")


                    # После клика дождаться пока опубликуется
                    WebDriverWait(driver, 500).until(lambda x: not driver.find_elements(By.XPATH, "//*[text()='Публикация']"))
                    
                    del add_dialogs[index]

                    break  # После отправки формы список диалоговых окон нужно получать заново, т.к. самого верхнего окна в списке больше не осталось

            except TimeoutException:
                print(f"Ошибка добавления: таймаут")
                break

        if add_dialogs:
            print("Сброс счетчиков для текущего блока файлов")
            for file in files:
                index_file -= 1
                index_to_album -= 1
                size_to_album -= file[1][1]

            driver.refresh()
                    
            print("Идем грузить блок файлов заново")
            continue

        print("Сохранение списка фото успешно, идем за новым списком")
        break

    check_connection(driver)
    submit_button = driver.find_element(By.XPATH, "//*[text()='К альбому' or text()='Сохранить']")
    submit_label = driver.find_element(By.XPATH, "//*[@aria-label='К альбому' or @aria-label='Сохранить']")

    #todo найти проект образец и перестроить архитектуру

    while True:
        check_connection(driver)
        sleep(1)
        try:
            if submit_label.get_attribute('aria-disabled'):
                continue

            submit_button.click()
        except WebDriverException:
            continue
        print("Отправка формы")
        break

    save_progress(album_id, index_file, get_album_name())

@print_function_name
def get_album_name(driver: WebDriver = None, album_id: int = None) -> str:
    """
    Ввести название альбома
    :param driver:
    :type album_id: object
    :rtype: str
    :return: 
    """
    global album_name

    if driver and album_id:
        current_page = driver.current_url
        driver.get(f"{home}media/set/edit/a.{album_id}")
        album_name = WebDriverWait(driver, 100).until(EC.presence_of_element_located((By.XPATH, "//input[@type='text']"))).get_attribute("value")
        driver.get(current_page)

        return album_name
    else:
        if album_name and album_name != "":
            return album_name
        else:
            album_name = folder.split("\\")
            album_name = list(filter(None, album_name))

            del album_name[0]
            del album_name[0]
            album_name = '\\'.join(album_name)
            album_name = album_name.replace('\\\\', '\\')

            return album_name

@print_function_name
def create_album(driver: WebDriver, album_name, files: list[str]):
    """
    Creates an album in the media management interface by uploading files, specifying album name, and handling errors
    during file uploads. This function ensures that the album is properly created with its unique identifier and descriptive
    name while managing potential issues arising from problematic file uploads.

    :param album_name:
    :param driver: WebDriver instance used to interact with the web page for creating the album.
    :type driver: WebDriver
    :param files: List of file paths to be uploaded as part of the album.
    :type files: list[str]
    :return: A tuple containing the album's unique identifier as an integer and its descriptive name as a string.
    :rtype: tuple[int, str]
    """
    print(inspect.currentframe().f_code.co_name.replace("_", " "))
    global index_file, index_to_album

    check_connection(driver)
    driver.get(home + "media/set/create")

    check_connection(driver)
    files_input = WebDriverWait(driver, 100).until(EC.presence_of_element_located((By.XPATH, "//input[@type='file']")))
    set_files_to_field(files_input, files)

    check_connection(driver)
    elem = driver.find_element(By.XPATH, "//input[@type='text']")
    elem.send_keys(album_name)
    print(f"Название альбома: {album_name}")

    # @todo релоад стрницы, если есть подозрение что страница зависла или не прогрузилась
    
    # Дождаться загрузки файлов и нажать кнопку создания альбома
    check_connection(driver)
    submit_button = driver.find_element(By.XPATH, "//*[text()='Отправить']")
    submit_label = driver.find_element(By.XPATH, "//*[@aria-label='Отправить']")

    retry_count = 0
    popup_count = 0
    while True:
        check_connection(driver)
        popup_text = check_popups(driver)
        if popup_text:
            print(f"Обнаружен попап {popup_text}")
            print_progress_bar(size_to_album, size_all_files, prefix='Текущий прогресс:', suffix='Complete', length=50)
            popup_count += 1
            sleep_throttling(popup_count)
            print(f"Ошибок добавления: {popup_count}")

        # проверка на ошибки загрузки отдельных файлов
        try:
            repeat_button = driver.find_element(By.XPATH, "//*[text()='Повторить попытку']")
            repeat_button.click()
            retry_count += 1
            print(f"Повторная загрузка файлов с ошибками. Попытка {retry_count}")
        except NoSuchElementException:
            pass
        except WebDriverException:
            retry_count += 1

        sleep(1)

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

            album_description = driver.find_element(By.XPATH, "//*[text()='Описание (необязательно)']").find_element(By.XPATH, "..").find_element(By.XPATH, '//textarea')
            album_description.send_keys(album_name)

            submit_button.click()
        except WebDriverException:
            continue

        print("Отправка формы")

        break

    check_connection(driver)
    wait = WebDriverWait(driver, 100)
    wait.until(lambda x: driver.current_url.find('&set=') != -1) # ожидание когда завершится перенаправление на страницу созданного альбома

    query_def = parse.parse_qs(parse.urlparse(driver.current_url).query).get('set')[0]
    album_id = query_def.lstrip('a.')
    save_progress(album_id, index_file, album_name)

    return int(album_id)

@print_function_name
def set_album_confidentiality(driver: WebDriver, album_id: int):
    """
    Изменить видимость альбома
    :param driver:
    :param album_id:
    """

    check_connection(driver)
    problems_count = 0
    while True:
        check_connection(driver)
        popup_text = check_popups(driver)
        if popup_text:
            print(f"Обнаружен попап {popup_text}")
            problems_count += 1
            sleep_throttling(problems_count)
            continue
        else:
            break
    
    check_connection(driver)
    print('Настройка видимости альбома')
    driver.get(f"{home}media/set/edit/a.{album_id}")
    button = WebDriverWait(driver, 100).until(EC.presence_of_element_located((By.XPATH, "//*[contains(@aria-label,'Изменить конфиденциальность.')]")))
    button.click()
    WebDriverWait(driver, 100).until(EC.presence_of_element_located((By.XPATH, "//*[text()='Выберите аудиторию']")))
    button = driver.find_element(By.XPATH, "//div[@aria-label='Выберите аудиторию']//*[text()='Только я']")
    button.click()
    button = driver.find_element(By.XPATH, "//div[@aria-label='Выберите аудиторию']//*[text()='Готово']")
    button.click()
    submit_button = driver.find_element(By.XPATH, "//*[text()='К альбому' or text()='Сохранить']")
    submit_button.click()

@print_function_name
def parse_cli_args():
    """
    Пример ввода
    run.py --folder "D:\\PHOTO\\Домашние\\АРХИВЫ\\РАЗНОЕ\\Мамина работа\\к педсовету" --renewcookie --splitedsize=30
    run.py --folder "Стар. фото из Протасово -родня" --splitedsize=10 --rootfolder "D:\\PHOTO"
    run.py --folder "Фото 2009 г" --splitedsize=10 --rootfolder "D:\\PHOTO" --headless
    run.py --folder "Хабаровск" --splitedsize=10 --rootfolder D:\\PHOTO --headless --recursive
    run.py --folder "Домашние" --splitedsize=10 --rootfolder D:\\PHOTO --checkduplicates
    run.py --folder "аэропорт Симферополь Москва" --splitedsize=10 --rootfolder D:\\PHOTO --headless
    run.py --folder "Узбекистан" --splitedsize=3 --rootfolder G:\\PHOTO
    run.py --folder "Узбекистан" --splitedsize=1 --rootfolder G:\\PHOTO --headless
    run.py --folder "Узбекистан" --splitedsize=5 --rootfolder G:\\PHOTO --headless --albumid=4003113339960597

    """
    global folder, renew_cookie, splited_size, root_folder, is_headless, check_duplicates, recursive, album_id

    parser = argparse.ArgumentParser()
    parser.add_argument('--folder', dest='folder', type=str, help='Full path to the folder', required=True)
    parser.add_argument('--splitedsize', help='How many files to send to the album per iteration', type=int, default=20)
    parser.add_argument('--rootfolder', help='Root folder for target folder', type=str)
    parser.add_argument('--headless', help='Run without any GUI', action="store_true")#todo очистку прогресса добавить
    parser.add_argument('--renewcookie', help='Force renew cookie', action="store_true")
    parser.add_argument('--checkduplicates', help='Check for duplicates before uploading', action="store_true")
    parser.add_argument('--recursive', help='Search files in subfolders', action="store_true")
    parser.add_argument('--albumid', help='Album id for upload', type=int)
    args = parser.parse_args()
    folder = args.folder
    renew_cookie = args.renewcookie
    splited_size = args.splitedsize
    root_folder = args.rootfolder
    is_headless = args.headless
    check_duplicates = args.checkduplicates
    recursive = args.recursive
    album_id = args.albumid

#todo надо проверить клик по окну "Вы врененно заблокированы", возможно он не работает
#todo если время паузы стало очень большое, то пробуем ребутнуть страницу и загрузить заново

def print_progress_bar(iteration, total, prefix = '', suffix = '', decimals = 1, length = 100, fill = '█'):
    """
    Call in a loop to create terminal progress bar
    @params:
        iteration   - Required  : current iteration (Int)
        total       - Required  : total iterations (Int)
        prefix      - Optional  : prefix string (Str)
        suffix      - Optional  : suffix string (Str)
        decimals    - Optional  : positive number of decimals in percent complete (Int)
        length      - Optional  : character length of bar (Int)
        fill        - Optional  : bar fill character (Str)
    """
    percent = ("{0:." + str(decimals) + "f}").format(100 * (iteration / float(total)))
    filledLength = int(length * iteration // total)
    bar = fill * filledLength + '-' * (length - filledLength)
    print(f"{prefix} |{bar}| {percent}% {suffix}")
    # Print New Line on Complete
    if iteration == total:
        print()

@print_function_name
def set_files_to_field(files_input: WebElement, files: list):
    global index_file, index_to_album, count_all_files, size_to_album, size_all_files

    # Initial call to print 0% progress
    print_progress_bar(size_to_album, size_all_files, prefix='Progress:', suffix='Complete', length=50)

    for file in files:
        ipath = file[1][-1]
        print(f"Загрузка фото: {file[1][0]} {size(file[1][1])}")
        files_input.send_keys(ipath)
        sys.stdout.flush()
        index_file += 1
        index_to_album += 1
        size_to_album += file[1][1]
        print(
            f"Загружено {index_to_album} фото из {count_all_files} ({size(size_to_album)} из {size(size_all_files)})",
            flush=True
        )
        print_progress_bar(size_to_album, size_all_files, prefix='Progress:', suffix='Complete', length=50)
        sleep(0.2)

@print_function_name
def check_popups(driver):
    """
    Попапы "Мы удалили вашу публикацию" и "Вы временно заблокированы" обрабатывать
    :param driver:
    """
    need_return = False
    popup_text = None
    try:
        popup = driver.find_element(By.XPATH, "//*[text()='Вы временно заблокированы' or text()='Мы удалили вашу публикацию' or text()='Что произошло']")
        popup_text = popup.text
        buttons = driver.find_elements(By.XPATH, "//*[text()='OK' or @aria-label='Закрыть']")

        for button in buttons:
            try:
                button.click()
            except WebDriverException:
                continue
            
            need_return = False
            break

    except WebDriverException:
        need_return = True


    if need_return:
        return False

    return popup_text

@print_function_name
def search_folder_recursive(folder: str, root_path: str = '.') -> str|None:
    """

    :return:
    :rtype: object
    :return:
    :param root_path:
    :type folder: object
    """

    def listdir_r(dirpath, searching_folder):
        paths = []
        for path in listdir(dirpath):
            rpath = join(dirpath, path)
            if isdir(rpath):
                if searching_folder == path:
                    paths.append(rpath)
                    break
                else:
                    subdirs = listdir_r(rpath, searching_folder)
                    if not subdirs == []:
                        paths.extend(subdirs)
        return paths if paths else []

    paths = listdir_r(root_path, folder)

    return paths[0] if paths else None

def get_hash(f):
    # BUF_SIZE is totally arbitrary, change for your app!
    BUF_SIZE = 65536  # lets read stuff in 64kb chunks!

    md5 = hashlib.md5()

    with open(f, 'rb') as f:
        while True:
            data = f.read(BUF_SIZE)
            if not data:
                break
            md5.update(data)

    return md5.hexdigest()

@print_function_name
def get_files_size(files: list, print: bool = True) -> int|str:
    files_sizes = [size for _, (_, size, _) in files]
    return size(sum(files_sizes)) if print else sum(files_sizes)

@print_function_name
def get_profile_id(driver):
    global profile_id

    if profile_id and profile_id != 0:
        return profile_id
    else:
        # Найти все ссылки на странице
        links = driver.find_elements(By.TAG_NAME, 'a')

        # Проверить ссылки на наличие "https://www.facebook.com/profile.php?id="
        for link in links:
            href = link.get_attribute('href')
            if href and home + "profile.php?id=" in href and link.text == profile_name:
                parsed_url = parse.urlparse(href)
                profile_id = parse.parse_qs(parsed_url.query).get("id", [None])[0]
        return profile_id
#todo кэш для вычисленных значений

@print_function_name
def find_album(driver: WebDriver, album_name):
    """
    https://www.facebook.com/profile.php?id=100007859116486&sk=photos_albums
    @todo поиск альбома сделать опциональным
    @todo оптимизировать поиск, чтобы искал в процессе прокрутки
    """
    driver.get(f"{home}profile.php?id={get_profile_id(driver)}&sk=photos_albums")

    scroll_to_end(driver)

    # Далее ищем текст внутри span
    try:
        """
        Этот вариант корректно работает для случаев: 
        ✅ "album_name"
        ✅ "album_name 2"
        ✅ "album_name 15"
        ❌ "album_name xyz" (отфильтрует, так как нет числа в конце)
        """
        span_elements = driver.find_elements(By.XPATH,f"//span[text()='{album_name}' or (starts-with(text(), '{album_name} ') and text()[string-length() - string-length(translate(text(), '0123456789', ''))] > 0)]")
        span_element = span_elements[-1]
    except NoSuchElementException:
        return None

    # Найти родителя ссылку и выдернуть id из выражения href="https://www.facebook.com/media/set/?set=a.3784912368447363&type=3"
    parent_link = span_element.find_element(By.XPATH, "./ancestor::a")
    count_text = parent_link.find_element(By.XPATH, f"//*[contains(text(), 'объекта')]")
    number = int(re.sub(r"\D", "", count_text))

    # Извлечь id из href
    href = parent_link.get_attribute("href")
    match = re.search(r"set=a\.(\d+)", href)
    if match:
        media_id = match.group(1)
        return (media_id, number)
    else:
        return None

@print_function_name
def scroll_to_end(driver: WebDriver, pause_time=3):
    """
    Функция для прокрутки страницы до конца и проверки, что прокрутка завершена.
    """

    # Найти элемент body для прокрутки страницы
    body = driver.find_element(By.TAG_NAME, 'body')

    #last_height = driver.execute_script("return document.body.scrollHeight")

    while can_scroll_down(driver):
        body.send_keys(Keys.SPACE)
        sleep(pause_time)  # Небольшая задержка, чтобы страница успела прогрузиться

@print_function_name
def wait_for_page_load(driver: WebDriver, timeout=1):
    """
    Функция для ожидания окончания загрузки страницы
    Ожидание, пока document.readyState станет 'complete'.
    """
    start_time = time.time()
    while time.time() - start_time < timeout:
        page_state = driver.execute_script("return document.readyState;")
        if page_state == "complete":
            print("Загрузка страницы завершена.")
            return True
        time.sleep(0.5)
    print("Тайм-аут: страница не загрузилась полностью.")
    return False

def can_scroll_down(driver):
    """ Функция для проверки возможности дальнейшей прокрутки вниз """
    current_scroll = driver.execute_script("return window.scrollY + window.innerHeight;")
    total_height = driver.execute_script("return document.body.scrollHeight;")
    return current_scroll < total_height


@print_function_name
def wait_for_element(driver: WebDriver, by: str, timeout: int = 1) -> None:
    """

    :param driver: 
    :param by: 
    :param timeout: 
    """
    while True:
        sleep(timeout)
        try:
            driver.find_element(By.XPATH, by)
        except WebDriverException:
            continue
        break

def check_connection(driver: WebDriver):
    """
    распознавать сообщение об отсуствии интернета и ставить процесс на паузу
    """
    while True:
        if connection_status == False:
            try:
                WebDriverWait(driver, 500).until(lambda x: connection_status == True)
            except TimeoutException:
                continue    
            break
        break


def main():
    global index_file, folder, size_all_files, count_all_files, album_id
    # todo проверка если куки истекли, но по факту авторизаци с ними произошал успешно

    # Your Facebook account user and password
    usr = config.USER_NAME
    pwd = config.PASSWORD

    if not usr or not pwd:
        print("Error: Missing Facebook credentials.")
        sys.exit(1)
    #cookie_filename = usr + ' ' + cookie_filename todo в название файла логин добавить
    #todo Эта публикация нарушает наши Нормы сообщества - это сообщение обрабатывать
    #todo Не удалось опубликовать фото - обрабатывать попап-ошибку - это такой же попап как и Вы временно заблокированы
    #todo Вы временно заблокированы - страница /media/set/edit/a.3967419006863364

    parse_cli_args()

    driver = get_driver()

    # Go to facebook.com
    driver.get(home)

    Watcher(driver)

    is_authorized = False
    # todo после сокрытия попапа "Что произошло" паузу не делать
    
    if add_cookies(driver, cookie_filename):
        driver.get(home)
        
    driver.refresh()
    is_authorized = check_page(driver, 'index')
    
    if renew_cookie or not is_authorized:
        if check_page(driver, 'login'):
            login(driver, usr, pwd)
        else:
            driver.get(home)
            login(driver, usr, pwd)

        index = 0
        while True:
            if check_page(driver, 'captcha'):
                solve_captcha(driver)
            else:
                break

            index += 1
            if index > 30:
                driver.close()
                sys.exit('Капча не решена')

        if check_page(driver, 'two_step_verification'):
            two_step_verification_wait(driver)
        if check_page(driver, 'add_trusted_device'):
            add_trusted_device(driver)
        save_cookies(driver, cookie_filename)


    driver.refresh()

    #todo пройтись по структуре папок и собрать папки на аплоад и создание альбомов

    if folder.split('\\').__len__() == 1:
        # Задано только название папки, а не полный путь - найти папку
        folder = search_folder_recursive(folder, root_folder.replace('\\\\', '\\') if root_folder else 'D:\\')

    print(f"Полный путь к папке {folder}")
    #todo при заблокированности теймер до повторной попытки выводить

    files = {
        (get_hash(join(root, f)) if check_duplicates else join(root, f)): (
        f, os.path.getsize(join(root, f)), join(root, f))
        for root, _, filenames in (os.walk(folder) if recursive else [(folder, [], listdir(folder))])
        for f in filenames
        if isfile(join(root, f))
           and filetype.is_image(join(root, f))
           and os.path.splitext(f)[1].lower() not in ['.psd', '.mpo', '.thm']
    }

    driver.get(home)

    #files {id: (название, размер, полное название)}
    if files:
        files = [(id, (name, size, full_name)) for id, (name, size, full_name) in files.items()]
        # files [(id, (название, размер, полное название))]
        all_files = files.copy()

        progress = restore_progress()
        if progress:
            index_file = progress[1]
            del files[0:index_file]

        count_all_files = len(files)
        if count_all_files == 0:
            files = all_files
        count_all_files = len(files)

        size_all_files = get_files_size(files, False)
        size_all_files_formatted = get_files_size(files, True)

        print(f"Найдено файлов для загрузки {count_all_files} {size_all_files_formatted}")

        files_splited = [files[x:x + splited_size] for x in range(0, len(files), splited_size)]

        if album_id:# задан в параметрах при запуске
            album_name = get_album_name(driver, album_id)
        else:
            if not progress:
                # Создание альбома и загрузка файлов
                album_name = get_album_name()
                wait_for_element(driver, "//*[@aria-label=\"Поиск на Facebook\"]")
                album_id, count_photo_in_album = find_album(driver, album_name)

                if count_photo_in_album >= 3000: #todo в конфиг
                    album_id = None

                if not album_id:
                    print(f"Альбом {album_name} не найден")
                    album_id = create_album(driver, album_name, files_splited[0])
                    del files_splited[0]
                    print(f"Альбом {album_name} добавлен, ID альбома {album_id}")
                    set_album_confidentiality(driver, album_id)
                else:
                    print(f"Альбом {album_name} найден, ID альбома {album_id}")

            else:
                album_id = progress[0] #todo создать реестр в котором хранить информацию о заполненности альбомов и остальную информацию, которую можно не вычислять заново
                album_name = progress[2]


        print(f"Название альбома: {album_name}, ID альбома: {album_id}")

        while True:
            if not files_splited:
                clear_saved_progress()
                break
            upload_to_album(driver, album_id=album_id, files=files_splited[0])
            del files_splited[0]

        print("Загрузка завершена\n")
        print(f"Название альбома: {album_name}")
        print(f"ID альбома: {album_id}")
        print(f"Загружено файлов: {count_all_files} {size_all_files_formatted}")
    else:
        # если файлы для загрузки не найдены, сообщение об этом выводить
        print("Файлы для загрузки не найдены")

    clear_saved_progress()

    sleep(20)

    driver.close()# todo в wait паузы увеличить

class Inp:
    inp = None

    def __init__(self, hint=None):
        t = Thread(target=self.get_input, args=(hint,))
        t.daemon = True
        t.start()
        t.join(timeout=500)

    def get_input(self, hint):
        self.inp = input(hint)

    def get(self):
        return self.inp


class Watcher:
    instance = None
    problems_count = 0

    def __init__(self, driver):
        t = Thread(target=self.check_page_unavailable, args=(driver,))
        t.daemon = True
        t.start()

        t2 = Thread(target=self.check_connection_lost, args=(driver,))
        t2.daemon = True
        t2.start()

        t3 = Thread(target=self.check_connection_stable, args=(driver,))
        t3.daemon = True
        t3.start()

    def check_page_unavailable(self, driver):
        while True:
            try: 
                element = WebDriverWait(driver, 100).until(EC.presence_of_element_located((By.XPATH, "//*[text()='Страница сейчас недоступна']")))
                print(f'Watcher: обнаружено сообщение {element.text}')
                self.problems_count += 1
                sleep(100)
                driver.refresh()
            except TimeoutException:
                self.problems_count = 0
                pass
    
    def check_connection_lost(self, driver):
        global connection_status
        while True:
            try: 
                element = WebDriverWait(driver, 1000).until(EC.presence_of_element_located((By.XPATH, "//*[text()='Вы офлайн.']")))
                if connection_status == True:
                    print(f'Watcher: обнаружено сообщение {element.text}')
                    print('Watcher: соединение потеряно')
                    connection_status = False
            except WebDriverException:
                pass
    
    def check_connection_stable(self, driver):
        global connection_status
        while True:
            try: 
                element = WebDriverWait(driver, 1000).until(EC.invisibility_of_element_located((By.XPATH, "//*[text()='Вы офлайн.']")))
                if connection_status == False:
                    print('Watcher: соединение восстановлено')
                    connection_status = True
            except WebDriverException:
                pass

if __name__ == '__main__':
    main()
