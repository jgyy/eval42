# 42 Singapore User Fetcher

## Prerequisites

- Python 3.8+
- pip (Python package manager)

## Setup

1. Clone this repository
2. Create a virtual environment (recommended):
   ```
   python -m venv venv
   source venv/bin/activate
   ```

3. Install dependencies:
   ```
   pip install -r requirements.txt
   ```

## Getting 42 API Credentials

1. Go to https://profile.intra.42.fr/oauth/applications
2. Click "New Application"
3. Fill in the details:
   - Name: 42 Singapore User Fetcher
   - Redirect URI: http://localhost:8080
4. Create the application
5. Copy the Client ID and Client Secret

## Running the Application

```
python user_fetcher.py
```

## Configuration

Create a `.env` file in the same directory as the script with the following content:

```
FORTYTWO_CLIENT_ID=your_client_id_here
FORTYTWO_CLIENT_SECRET=your_client_secret_here
```

## Usage

1. Configure your `.env` file with 42 API credentials
2. Run the application
3. Click "Fetch Users"
4. View the list of users from 42 Singapore

Alternatively, you can manually enter credentials in the application interface.

## Notes

- The application fetches users from the 42 Singapore campus
- It displays login, name, email, and staff status
- Users are fetched in batches to handle large numbers of users
- Credentials can be stored in .env file or entered manually
