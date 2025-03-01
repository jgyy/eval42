import sys
import os
import requests
import logging
from dotenv import load_dotenv
from PyQt5.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, 
                             QLabel, QPushButton, QTableWidget, 
                             QTableWidgetItem, QMessageBox, QProgressBar, QWidget)
from PyQt5.QtCore import Qt, QThread, pyqtSignal

logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(levelname)s - %(message)s',
                    handlers=[
                        logging.FileHandler("user_fetcher.log"),
                        logging.StreamHandler()
                    ])

load_dotenv()

class UserFetchThread(QThread):
    users_fetched = pyqtSignal(list)
    error_occurred = pyqtSignal(str)
    progress_updated = pyqtSignal(str)

    def __init__(self, client_id, client_secret):
        super().__init__()
        self.client_id = client_id
        self.client_secret = client_secret

    def run(self):
        try:
            self.progress_updated.emit("Authenticating with 42 API...")
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
            
            self.progress_updated.emit("Fetching initial user data...")
            
            filter_params = {
                "page[number]": 1,
                "page[size]": 100,
                "filter[primary_campus_id]": 28,
                "filter[staff?]": "false"
            }
            url = f"{base_url}/users"
            logging.info(f"Fetching users with params: {filter_params}")
            
            response = requests.get(url, 
                                    headers=headers, 
                                    params=filter_params)
            
            logging.info(f"Response status: {response.status_code}")
            
            response.raise_for_status()
            
            users = response.json()
            logging.info(f"Fetched {len(users)} users")
            
            self.progress_updated.emit("Fetch complete. Processing results...")
            self.users_fetched.emit(users)
        
        except requests.RequestException as e:
            logging.error(f"Request failed: {e}")
            self.error_occurred.emit(str(e))
        except Exception as e:
            logging.error(f"Unexpected error: {e}")
            self.error_occurred.emit(str(e))

class UserFetcherApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.client_id = os.getenv('FORTYTWO_CLIENT_ID', '')
        self.client_secret = os.getenv('FORTYTWO_CLIENT_SECRET', '')
        
        if not self.client_id or not self.client_secret:
            logging.error("Missing client credentials")
        
        self.initUI()

    def initUI(self):
        self.setWindowTitle('42 Singapore User Fetcher')
        self.setGeometry(100, 100, 800, 600)

        main_layout = QVBoxLayout()

        # Progress description label
        self.progress_label = QLabel('Ready to fetch users')
        self.progress_label.setAlignment(Qt.AlignCenter)

        self.fetch_button = QPushButton('Fetch Users')
        self.fetch_button.clicked.connect(self.start_fetch)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)

        self.user_table = QTableWidget()
        self.user_table.setColumnCount(4)
        self.user_table.setHorizontalHeaderLabels(['Login', 'Name', 'Email', 'Campus'])

        main_layout.addWidget(self.progress_label)
        main_layout.addWidget(self.fetch_button)
        main_layout.addWidget(self.progress_bar)
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
        self.progress_bar.setVisible(False)
        self.fetch_button.setEnabled(True)
        self.progress_label.setText(f'Fetched {len(users)} users')

        self.user_table.setRowCount(len(users))
        for row, user in enumerate(users):
            login_item = QTableWidgetItem(user.get('login', 'N/A'))
            self.user_table.setItem(row, 0, login_item)

            name_item = QTableWidgetItem(user.get('usual_full_name', 'N/A'))
            self.user_table.setItem(row, 1, name_item)

            email_item = QTableWidgetItem(user.get('email', 'N/A'))
            self.user_table.setItem(row, 2, email_item)

            campus_names = [campus.get('name', 'N/A') for campus in user.get('campus', [])]
            campus_item = QTableWidgetItem(', '.join(campus_names))
            self.user_table.setItem(row, 3, campus_item)

        self.user_table.resizeColumnsToContents()

    def update_progress(self, message):
        self.progress_label.setText(message)

    def show_error(self, error_message):
        self.progress_bar.setVisible(False)
        self.fetch_button.setEnabled(True)
        self.progress_label.setText('Error occurred')
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
