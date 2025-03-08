require('dotenv').config();
const axios = require('axios');
const fs = require('fs');

const CLIENT_ID = process.env.FORTYTWO_CLIENT_ID;
const CLIENT_SECRET = process.env.FORTYTWO_CLIENT_SECRET;
const BASE_URL = 'https://api.intra.42.fr';
const CAMPUS_ID = 64;
const CURSUS_ID = 21;
const NON_STAFF_FILE = 'student_users.json';

async function main() {
  try {
    const token = await getOAuthToken();
    const studentUsers = await fetchAllStudents(token);

    const filteredUsers = studentUsers.map(user => ({
      id: user.id,
      level: user.level,
      grade: user.grade,
      cursus_id: user.cursus_id,
      blackholed_at: user.blackholed_at,
      user: {
        login: user.user.login,
        name: user.user.usual_full_name || `${user.user.first_name} ${user.user.last_name}`,
        wallet: user.user.wallet,
        status: user.user.alumni ? 'Alumni' : (user.user.active ? 'Active' : 'Inactive'),
        pool_month: user.user.pool_month,
        pool_year: user.user.pool_year
      }
    }));

    fs.writeFileSync(NON_STAFF_FILE, JSON.stringify(filteredUsers, null, 2));
    console.log(`Successfully fetched and filtered ${filteredUsers.length} student users`);
    console.log(`Results saved to ${NON_STAFF_FILE}`);
  } catch (error) {
    console.error('Error:', error.response ?
      `${error.message} - ${JSON.stringify(error.response.data)}` :
      error.message);
    process.exit(1);
  }
}

async function getOAuthToken() {
  try {
    const response = await axios.post(`${BASE_URL}/oauth/token`, {
      grant_type: 'client_credentials',
      client_id: CLIENT_ID,
      client_secret: CLIENT_SECRET
    });
    return response.data.access_token;
  } catch (error) {
    console.error('Failed to obtain OAuth token:',
      error.response ? JSON.stringify(error.response.data) : error.message);
    throw error;
  }
}

async function fetchAllStudents(token) {
  let page = 1;
  const perPage = 100;
  let allStudents = [];
  let hasMorePages = true;

  console.log('Fetching all student users with level > 0...');

  while (hasMorePages) {
    try {
      console.log(`Fetching page ${page}...`);

      const response = await axios.get(`${BASE_URL}/v2/cursus/${CURSUS_ID}/cursus_users`, {
        headers: {
          Authorization: `Bearer ${token}`
        },
        params: {
          'filter[campus_id]': CAMPUS_ID,
          'range[level]': '4,30',
          'sort': '-level',
          'page[size]': perPage,
          'page[number]': page
        }
      });

      const users = response.data;
      if (users.length === 0) {
        hasMorePages = false;
      } else {
        allStudents = allStudents.concat(users);
        page++;
        await new Promise(resolve => setTimeout(resolve, 500));
      }
    } catch (error) {
      if (error.response) {
        if (error.response.status === 429) {
          const retryAfter = error.response.headers['retry-after'] || 5;
          console.log(`Rate limited. Waiting for ${retryAfter} seconds...`);
          await new Promise(resolve => setTimeout(resolve, retryAfter * 1000));
        } else {
          console.error(`API Error: ${error.response.status} - ${JSON.stringify(error.response.data)}`);
          throw error;
        }
      } else {
        throw error;
      }
    }
  }

  return allStudents;
}

main();
