import sys
import os
import json
import requests
import logging
import time
from datetime import datetime
from dotenv import load_dotenv
from PyQt5.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, 
                             QLabel, QPushButton, QTableWidget, QLineEdit,
                             QTableWidgetItem, QMessageBox, QProgressBar, QWidget)
from PyQt5.QtCore import QObject, QThread, pyqtSignal, Qt
from PyQt5.QtGui import QPixmap, QColor

logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(levelname)s - %(message)s',
                    handlers=[
                        logging.FileHandler("user_fetcher.log"),
                        logging.StreamHandler()
                    ])
load_dotenv()
SINGAPORE_CAMPUS_ID = 64
DATA_FILE = "42_users_data.json"

class ImageDownloader(QObject):
    image_downloaded = pyqtSignal(QPixmap)
    error_occurred = pyqtSignal()
    finished = pyqtSignal()
    
    def __init__(self, url):
        super().__init__()
        self.url = url
    
    def run(self):
        try:
            response = requests.get(self.url, timeout=10)
            if response.status_code == 200:
                pixmap = QPixmap()
                if pixmap.loadFromData(response.content):
                    if not pixmap.isNull() and pixmap.width() > 0 and pixmap.height() > 0:
                        self.image_downloaded.emit(pixmap)
                    else:
                        logging.warning(f"Failed to create valid pixmap from {self.url}")
                        self.error_occurred.emit()
                else:
                    logging.warning(f"Failed to load image data from {self.url}")
                    self.error_occurred.emit()
            else:
                logging.warning(f"Failed to download image: HTTP {response.status_code} from {self.url}")
                self.error_occurred.emit()
        except Exception as e:
            logging.error(f"Error downloading image from {self.url}: {e}")
            self.error_occurred.emit()
        finally:
            self.finished.emit()

class UserFetchThread(QThread):
    users_fetched = pyqtSignal(list)
    error_occurred = pyqtSignal(str)
    progress_updated = pyqtSignal(str, int)

    def __init__(self, client_id, client_secret):
        super().__init__()
        self.client_id = client_id
        self.client_secret = client_secret

    def run(self):
        max_retries = 3
        retry_delay = 2
        try:
            self.progress_updated.emit("Authenticating with 42 API...", 0)
            logging.info("Starting authentication process")
            token_url = "https://api.intra.42.fr/oauth/token"
            token_data = {
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret
            }
            token_response = requests.post(token_url, data=token_data)
            token_response.raise_for_status()
            access_token = token_response.json()['access_token']
            logging.info("Successfully obtained access token")
            headers = {"Authorization": f"Bearer {access_token}"}
            base_url = "https://api.intra.42.fr/v2"

            self.progress_updated.emit("Fetching Singapore campus ID...", 5)
            singapore_campus_id = self.fetch_singapore_campus_id(headers, base_url)
            logging.info(f"Using Singapore campus ID: {singapore_campus_id}")

            self.progress_updated.emit("Fetching coalitions data...", 10)
            coalitions = self.fetch_coalitions(headers, base_url)
            logging.info(f"Fetched {len(coalitions)} coalitions")
            all_users = []
            all_user_logins = []
            page = 1
            total_pages = 1
            while page <= total_pages:
                self.progress_updated.emit(
                    f"Fetching users page {page}/{total_pages}...",
                    int(10 + (page / total_pages * 40)) if total_pages > 1 else 20
                )
        
                retry_count = 0
                success = False
        
                while not success and retry_count < max_retries:
                    try:
                        filter_params = {
                            "page[number]": page,
                            "page[size]": 100,
                            "filter[primary_campus_id]": singapore_campus_id,
                            "filter[staff?]": "false",
                            "sort": "login"
                        }
                        url = f"{base_url}/users"
                        response = requests.get(url, headers=headers, params=filter_params)
                        response.raise_for_status()
                        success = True
                
                    except requests.RequestException as e:
                        retry_count += 1
                        if retry_count < max_retries:
                            wait_time = retry_delay * (2 ** (retry_count - 1))
                            logging.warning(f"Request failed, retrying in {wait_time} seconds: {e}")
                            self.progress_updated.emit(
                                f"API error, retrying in {wait_time}s ({retry_count}/{max_retries})...",
                                int(10 + ((page - 0.5) / total_pages * 40)) if total_pages > 1 else 30
                            )
                            time.sleep(wait_time)
                        else:
                            raise
                if 'X-Total' in response.headers and 'X-Per-Page' in response.headers:
                    total_users = int(response.headers['X-Total'])
                    per_page = int(response.headers['X-Per-Page'])
                    total_pages = (total_users + per_page - 1) // per_page

                users_page = response.json()
                logging.info(f"Fetched {len(users_page)} users from page {page}/{total_pages}")
                user_logins = [user.get('login') for user in users_page if user.get('login')]
                all_user_logins.extend(user_logins)
                all_users.extend(users_page)
                page += 1
                time.sleep(1)
            self.progress_updated.emit(f"Fetching coalition data for {len(all_user_logins)} users...", 50)
            coalition_users = self.fetch_coalition_users_batch(headers, base_url, all_user_logins, coalitions)
            for user in all_users:
                login = user.get('login')
                user_coalition = coalition_users.get(login, {})

                user['coalition_id'] = user_coalition.get('coalition_id')
                user['coalition_points'] = user_coalition.get('score', 0)
                user['coalition_name'] = user_coalition.get('name', 'N/A')
                user['coalition_color'] = user_coalition.get('color', '#CCCCCC')
                
            self.save_to_json(all_users)
            self.progress_updated.emit(f"Fetch complete. Retrieved {len(all_users)} users.", 100)
            self.users_fetched.emit(all_users)
        except requests.RequestException as e:
            logging.error(f"Request failed: {e}")
            self.error_occurred.emit(str(e))
        except Exception as e:
            logging.error(f"Unexpected error: {e}")
            self.error_occurred.emit(str(e))

    def fetch_coalitions(self, headers, base_url):
        """Fetch all coalitions once to avoid repeated API calls"""
        try:
            url = f"{base_url}/coalitions"
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            coalitions = {coalition['id']: coalition for coalition in response.json()}
            return coalitions
        except Exception as e:
            logging.error(f"Error fetching coalitions: {e}")
            return {}

    def fetch_coalition_users_batch(self, headers, base_url, user_logins, coalitions):
        """Fetch coalition data for multiple users more efficiently"""
        coalition_users = {}
        batch_size = 10
        
        try:
            for i in range(0, len(user_logins), batch_size):
                batch_logins = user_logins[i:i+batch_size]

                self.progress_updated.emit(f"Fetching coalition data for users {i+1}-{min(i+batch_size, len(user_logins))}...", 
                                        50 + int((i / len(user_logins)) * 30))

                for login in batch_logins:
                    url = f"{base_url}/users/{login}/coalitions_users"
                    try:
                        response = requests.get(url, headers=headers)
                        
                        if response.status_code == 200:
                            user_coalitions = response.json()
                            if user_coalitions and len(user_coalitions) > 0:
                                # Use the primary or first coalition
                                coalition_user = user_coalitions[0]
                                coalition_id = coalition_user.get('coalition_id')
                                if coalition_id:
                                    coalition_data = coalitions.get(coalition_id, {})
                                    coalition_users[login] = {
                                        'coalition_id': coalition_id,
                                        'score': coalition_user.get('score', 0),
                                        'name': coalition_data.get('name', 'N/A'),
                                        'color': coalition_data.get('color', '#CCCCCC')
                                    }
                    except Exception as e:
                        logging.error(f"Error fetching coalition data for user {login}: {e}")

                    time.sleep(0.2)

                    
        except Exception as e:
            logging.error(f"Error in coalition data batch processing: {e}")
        
        logging.info(f"Fetched coalition data for {len(coalition_users)} users")
        return coalition_users

    def fetch_singapore_campus_id(self, headers, base_url):
        try:
            url = f"{base_url}/campus"
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            
            campuses = response.json()
            for campus in campuses:
                if "Singapore" in campus.get('name', ''):
                    logging.info(f"Found Singapore campus with ID: {campus['id']}")
                    return campus['id']
            
            logging.warning("Singapore campus not found in the API response")
            return SINGAPORE_CAMPUS_ID
        except Exception as e:
            logging.error(f"Error fetching campus ID: {e}")
            return SINGAPORE_CAMPUS_ID

    def save_to_json(self, users):
        """Save fetched users to a JSON file with timestamp"""
        data = {
            "timestamp": datetime.now().isoformat(),
            "users": users
        }
        
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        
        logging.info(f"Saved {len(users)} users to {DATA_FILE}")

class UserFetcherApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.client_id = os.getenv('FORTYTWO_CLIENT_ID', '')
        self.client_secret = os.getenv('FORTYTWO_CLIENT_SECRET', '')
        
        if not self.client_id or not self.client_secret:
            logging.error("Missing client credentials")
        
        self.users = []
        self.initUI()
        self.load_cached_data()

    def initUI(self):
        self.setWindowTitle('42 Singapore User Fetcher')
        self.setGeometry(100, 100, 1200, 800)

        main_layout = QVBoxLayout()

        top_layout = QHBoxLayout()
        
        self.status_label = QLabel('Ready to fetch users')
        self.status_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        
        self.fetch_button = QPushButton('Fetch Users')
        self.fetch_button.clicked.connect(self.start_fetch)
        
        self.update_time_label = QLabel('No cached data')
        
        top_layout.addWidget(self.status_label, 3)
        top_layout.addWidget(self.update_time_label, 2)
        top_layout.addWidget(self.fetch_button, 1)
        
        main_layout.addLayout(top_layout)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        main_layout.addWidget(self.progress_bar)

        filter_layout = QHBoxLayout()
        self.filter_label = QLabel('Filter:')
        self.filter_input = QLineEdit()
        self.filter_input.setPlaceholderText('Enter filter text...')
        self.filter_input.textChanged.connect(self.apply_filter)
        
        filter_layout.addWidget(self.filter_label)
        filter_layout.addWidget(self.filter_input)
        main_layout.addLayout(filter_layout)

        self.user_table = QTableWidget()
        self.user_table.setColumnCount(10)
        self.user_table.setHorizontalHeaderLabels([
            'Profile', 'Login', 'Name', 'Email', 'Campus', 'Pool Year', 'Pool Month', 
            'Level', 'Wallet', 'Coalition Points'
        ])
        
        # Enable sorting
        self.user_table.setSortingEnabled(True)
        
        main_layout.addWidget(self.user_table)

        central_widget = QWidget()
        central_widget.setLayout(main_layout)
        self.setCentralWidget(central_widget)

    def start_fetch(self):
        if not self.client_id or not self.client_secret:
            QMessageBox.warning(self, 'Error', 'Client ID or Client Secret not configured in .env')
            logging.error("Credentials not configured")
            return
        self.user_table.setRowCount(0)
        self.fetch_thread = UserFetchThread(self.client_id, self.client_secret)
        self.fetch_thread.users_fetched.connect(self.display_users)
        self.fetch_thread.error_occurred.connect(self.show_error)
        self.fetch_thread.progress_updated.connect(self.update_progress)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)        
        self.fetch_button.setEnabled(False)
        self.fetch_thread.start()

    def display_users(self, users):
        self.users = users
        self.progress_bar.setVisible(False)
        self.fetch_button.setEnabled(True)
        self.status_label.setText(f'Fetched {len(users)} users')
        self.update_cached_time()
        self.user_table.setSortingEnabled(False)
        self.user_table.setRowCount(len(users))
    
        for row, user in enumerate(users):
            profile_pic_url = user.get('image_url', '')
            if profile_pic_url:
                pic_label = QLabel()
                pic_label.setAlignment(Qt.AlignCenter)
                if profile_pic_url.startswith('http:'):
                    profile_pic_url = profile_pic_url.replace('http:', 'https:')
                
                self.download_profile_pic(profile_pic_url, pic_label)
                self.user_table.setCellWidget(row, 0, pic_label)
            else:
                self.user_table.setItem(row, 0, QTableWidgetItem("No Image"))
            login_item = QTableWidgetItem(user.get('login', 'N/A'))
            self.user_table.setItem(row, 1, login_item)

            name_item = QTableWidgetItem(user.get('usual_full_name') or user.get('displayname', 'N/A'))
            self.user_table.setItem(row, 2, name_item)

            email_item = QTableWidgetItem(user.get('email', 'N/A'))
            self.user_table.setItem(row, 3, email_item)

            campus = "N/A"
            if 'campus' in user and user['campus'] and isinstance(user['campus'], list) and len(user['campus']) > 0:
                for campus_obj in user['campus']:
                    if isinstance(campus_obj, dict) and 'name' in campus_obj:
                        campus = campus_obj['name']
                        break
            elif 'campus' in user and user['campus'] and isinstance(user['campus'], dict) and 'name' in user['campus']:
                campus = user['campus']['name']
            elif 'campus_users' in user and len(user['campus_users']) > 0:
                for campus_user in user['campus_users']:
                    if 'campus' in campus_user and 'name' in campus_user['campus']:
                        if campus_user.get('is_primary', False):
                            campus = campus_user['campus']['name']
                            break
        
            campus_item = QTableWidgetItem(campus)
            self.user_table.setItem(row, 4, campus_item)
            pool_year = str(user.get('pool_year', 'N/A'))
            pool_year_item = QTableWidgetItem(pool_year)
            self.user_table.setItem(row, 5, pool_year_item)
        
            pool_month = str(user.get('pool_month', 'N/A'))
            pool_month_item = QTableWidgetItem(pool_month)
            self.user_table.setItem(row, 6, pool_month_item)
        
            level = "N/A"
            if 'cursus_users' in user and user['cursus_users']:
                for cursus_user in user['cursus_users']:
                    if cursus_user.get('cursus_id') == 21 or cursus_user.get('cursus', {}).get('id') == 21:
                        level = str(round(cursus_user.get('level', 0), 2))
                        break
                if level == "N/A" and len(user['cursus_users']) > 0:
                    level = str(round(user['cursus_users'][0].get('level', 0), 2))
        
            level_item = QTableWidgetItem(level)
            try:
                level_value = float(level.replace('N/A', '0'))
            except ValueError:
                level_value = 0
            level_item.setData(Qt.UserRole, level_value)
            self.user_table.setItem(row, 7, level_item)
        
            wallet = "N/A"
            if 'wallet' in user and user['wallet'] is not None:
                wallet = str(user['wallet'])
            wallet_item = QTableWidgetItem(wallet)
            try:
                wallet_value = int(wallet.replace('N/A', '0'))
            except ValueError:
                wallet_value = 0
            wallet_item.setData(Qt.UserRole, wallet_value)
            self.user_table.setItem(row, 8, wallet_item)
            coalition_points = str(user.get('coalition_points', 0))
            coalition_item = QTableWidgetItem(coalition_points)
            if 'coalition_color' in user and user['coalition_color']:
                coalition_item.setBackground(QColor(user['coalition_color']))
            
            try:
                coalition_value = int(coalition_points.replace('N/A', '0'))
            except ValueError:
                coalition_value = 0
            coalition_item.setData(Qt.UserRole, coalition_value)
            self.user_table.setItem(row, 9, coalition_item)

        self.user_table.resizeColumnsToContents()
        self.user_table.setSortingEnabled(True)

    def download_profile_pic(self, url, label):
        """Download profile picture asynchronously and set it on the label"""
        thread = QThread()
        worker = ImageDownloader(url)
        worker.moveToThread(thread)
        
        thread.started.connect(worker.run)
        worker.image_downloaded.connect(lambda pixmap: self.set_profile_pic(label, pixmap))
        worker.error_occurred.connect(lambda: label.setText("Error"))
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        
        thread.start()

    def set_profile_pic(self, label, pixmap):
        """Set the profile picture on the label"""
        scaled_pixmap = pixmap.scaled(40, 40, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        label.setPixmap(scaled_pixmap)

    def apply_filter(self, filter_text):
        """Filter table based on input text"""
        if not filter_text:
            for row in range(self.user_table.rowCount()):
                self.user_table.setRowHidden(row, False)
            return
        
        filter_text = filter_text.lower()
        
        # Check each row
        for row in range(self.user_table.rowCount()):
            match_found = False
            
            for col in range(1, self.user_table.columnCount()):
                item = self.user_table.item(row, col)
                if item and filter_text in item.text().lower():
                    match_found = True
                    break
            
            self.user_table.setRowHidden(row, not match_found)

    def load_cached_data(self):
        """Load user data from cached JSON file if available"""
        try:
            if os.path.exists(DATA_FILE):
                with open(DATA_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    
                self.update_time_label.setText(f"Last updated: {data['timestamp'][:19].replace('T', ' ')}")
                self.users = data['users']
                self.display_users(self.users)
                logging.info(f"Loaded {len(self.users)} users from cache")
        except Exception as e:
            logging.error(f"Error loading cached data: {e}")

    def update_cached_time(self):
        """Update the label showing when data was last cached"""
        try:
            if os.path.exists(DATA_FILE):
                with open(DATA_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    
                self.update_time_label.setText(f"Last updated: {data['timestamp'][:19].replace('T', ' ')}")
        except Exception as e:
            logging.error(f"Error updating cache time display: {e}")

    def update_progress(self, message, value):
        self.status_label.setText(message)
        self.progress_bar.setValue(value)

    def show_error(self, error_message):
        self.progress_bar.setVisible(False)
        self.fetch_button.setEnabled(True)
        self.status_label.setText('Error occurred')
        QMessageBox.critical(self, 'Error', f'Failed to fetch users: {error_message}')

def main():
    if os.environ.get('XDG_SESSION_TYPE') == 'wayland':
        os.environ['QT_QPA_PLATFORM'] = 'wayland'
    
    app = QApplication(sys.argv)
    ex = UserFetcherApp()
    ex.show()
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()
