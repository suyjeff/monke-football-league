from flask import Flask, render_template, jsonify
import requests
import sqlite3
from apscheduler.schedulers.background import BackgroundScheduler
from config import LEAGUE_ID, DB_NAME
import json
from collections import defaultdict

app = Flask(__name__)

# Database connection function
def get_db_connection():
    conn = sqlite3.connect('fantasy_football.db')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS teams
                 (id INTEGER PRIMARY KEY,
                  name TEXT,
                  conference TEXT,
                  wins INTEGER,
                  losses INTEGER,
                  points_for REAL,
                  points_against REAL,
                  waiver_budget INTEGER,
                  roster TEXT)''')
    conn.commit()
    conn.close()

import random

def update_data():
    # Fetch league data
    league_url = f"https://api.sleeper.app/v1/league/{LEAGUE_ID}"
    league_response = requests.get(league_url)
    league_data = league_response.json()

    # Fetch users data
    users_url = f"https://api.sleeper.app/v1/league/{LEAGUE_ID}/users"
    users_response = requests.get(users_url)
    users_data = users_response.json()

    # Fetch rosters data
    rosters_url = f"https://api.sleeper.app/v1/league/{LEAGUE_ID}/rosters"
    rosters_response = requests.get(rosters_url)
    rosters_data = rosters_response.json()

    # Fetch schedule data
    schedule_url = f"https://api.sleeper.app/v1/league/{LEAGUE_ID}/matchups/6"
    schedule_response = requests.get(schedule_url)
    print(f"Schedule Response Status Code: {schedule_response.status_code}")
    print(f"Schedule Response Content: {schedule_response.text[:200]}")  # Print first 200 characters
    
    try:
        schedule_data = schedule_response.json()
    except requests.exceptions.JSONDecodeError as e:
        print(f"JSONDecodeError: {e}")
        print(f"Full response content: {schedule_response.text}")
        # Handle the error appropriately, maybe set schedule_data to a default value
        schedule_data = {}
    
    # Calculate Luck-Adjusted Points For (LAPF)
    total_points = sum(roster['settings']['fpts'] for roster in rosters_data)
    average_points = total_points / len(rosters_data)
    
    # Calculate Strength of Schedule (SOS)
    schedule = defaultdict(list)
    for matchup in schedule_data:
        roster_id = int(matchup['roster_id'])  # Convert to integer
        opponent_id = int(matchup['matchup_id'])  # Assuming this should also be an integer
        
        if roster_id not in schedule:
            schedule[roster_id] = []
        
        schedule[roster_id].append(opponent_id)
    
    # Debug: Print schedule for a random team
    random_team_id = random.choice(list(schedule.keys()))
    print(f"Debug: Schedule for team {random_team_id}: {schedule[random_team_id]}")

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    for roster in rosters_data:
        user = next((user for user in users_data if user['user_id'] == roster['owner_id']), None)
        if user:
            # Calculate LAPF
            lapf = (roster['settings']['fpts'] - average_points) * 0.5 + average_points

            # Calculate SOS
            opponent_wins = sum(next((r['settings']['wins'] for r in rosters_data if r['roster_id'] == opp_id), 0) for opp_id in schedule[roster['roster_id']])
            sos = opponent_wins / len(schedule[roster['roster_id']]) if schedule[roster['roster_id']] else 0

            c.execute('''INSERT OR REPLACE INTO teams
                         (id, name, conference, wins, losses, points_for, points_against, waiver_budget, roster)
                         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                      (roster['roster_id'],
                       user['display_name'],
                       league_data['metadata'].get('division_' + str(roster['settings']['division']), 'Unknown'),
                       roster['settings']['wins'],
                       roster['settings']['losses'],
                       roster['settings']['fpts'],
                       roster['settings']['fpts_against'],
                       roster['settings']['waiver_budget_used'],
                       str(roster['players'])))

    conn.commit()
    conn.close()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/teams')
def get_teams():
    conn = get_db_connection()
    c = conn.cursor()
    
    c.execute('SELECT id, name, conference, wins, losses, points_for, points_against FROM teams')
    teams = c.fetchall()
    
    teams_list = []
    for team in teams:
        team_dict = dict(team)
        
        lapf, sos = get_advanced_stats(team_dict['id'])
        team_dict['luck_adjusted_points_for'] = round(lapf, 2)  # Round to 2 decimal places
        team_dict['strength_of_schedule'] = sos
        
        teams_list.append(team_dict)
    
    conn.close()
    return jsonify(teams_list)

# Add a new function to calculate and retrieve LAPF and SOS
def get_advanced_stats(team_id):
    lapf = lapf_scores.get(team_id, 0)
    sos = 0  # Placeholder for SOS calculation
    return lapf, sos

# Use this function when you need to display or use these stats
def get_team_data(team_id):
    c.execute("SELECT * FROM teams WHERE id = ?", (team_id,))
    team_data = c.fetchone()
    if team_data:
        lapf, sos = get_advanced_stats(team_id)
        return {**team_data, 'luck_adjusted_points_for': lapf, 'strength_of_schedule': sos}
    return None

def calculate_lapf_for_all_teams():
    conn = get_db_connection()
    c = conn.cursor()
    
    c.execute('SELECT id, points_for FROM teams')
    teams = c.fetchall()
    
    sorted_teams = sorted(teams, key=lambda x: x['points_for'], reverse=True)
    total_teams = len(teams)
    lapf_scores = defaultdict(float)
    
    for week in range(11):  # Assuming 11 weeks as per your previous explanation
        for i, team in enumerate(sorted_teams):
            lapf_scores[team['id']] += (total_teams - 1 - i) / (total_teams - 1)
    
    conn.close()
    return dict(lapf_scores)

# Global variable to store LAPF scores
lapf_scores = {}

def update_lapf_scores():
    global lapf_scores
    lapf_scores = calculate_lapf_for_all_teams()

if __name__ == '__main__':
    init_db()
    scheduler = BackgroundScheduler()
    scheduler.add_job(update_data, 'interval', hours=1)
    scheduler.start()
    update_data()  # Run once at startup
    update_lapf_scores()  # Calculate LAPF scores when the app starts
    app.run(debug=True)
