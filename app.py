from flask import Flask, render_template, jsonify
import requests
import sqlite3
from apscheduler.schedulers.background import BackgroundScheduler
from config import LEAGUE_ID, DB_NAME
import json
from collections import defaultdict
import random
import numpy as np
import os

app = Flask(__name__, template_folder=os.path.abspath('.'))

# Database connection function
def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    print("Database connection established")  # Debug print
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

# Global variables to store LAPF and SOS scores
lapf_scores = {}
sos_scores = {}

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

    teams = []
    for roster in rosters_data:
        user = next((user for user in users_data if user['user_id'] == roster['owner_id']), None)
        if user:
            # Calculate LAPF
            lapf = (roster['settings']['fpts'] - average_points) * 0.5 + average_points

            # Calculate SOS
            opponent_wins = sum(next((r['settings']['wins'] for r in rosters_data if r['roster_id'] == opp_id), 0) for opp_id in schedule[roster['roster_id']])
            sos = opponent_wins / len(schedule[roster['roster_id']]) if schedule[roster['roster_id']] else 0

            team = {
                'id': roster['roster_id'],
                'name': user['display_name'],
                'conference': league_data['metadata'].get('division_' + str(roster['settings']['division']), 'Unknown'),
                'wins': roster['settings']['wins'],
                'losses': roster['settings']['losses'],
                'points_for': roster['settings']['fpts'],
                'points_against': roster['settings']['fpts_against'],
                'waiver_budget': roster['settings']['waiver_budget_used'],
                'roster': str(roster['players'])
            }
            teams.append(team)

    for team in teams:
        c.execute('''INSERT OR REPLACE INTO teams (id, name, conference, wins, losses, points_for, points_against, waiver_budget, roster)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                  (team['id'], team['name'], team['conference'], team['wins'], team['losses'], team['points_for'], team['points_against'], team['waiver_budget'], team['roster']))
    
    print(f"Updated data for {len(teams)} teams")  # Debug print

    # After updating other data, calculate RPI and SOS scores
    global sos_scores
    _, sos_scores = calculate_rpi()

    conn.commit()
    conn.close()

def calculate_rpi():
    conn = get_db_connection()
    c = conn.cursor()
    
    c.execute('SELECT id, wins, losses FROM teams')
    teams = {row['id']: {'wins': row['wins'], 'losses': row['losses']} for row in c.fetchall()}
    
    remaining_schedule = get_remaining_schedule()
    
    rpi_scores = {}
    sos_scores = {}
    
    for team_id, team_data in teams.items():
        team_wp = team_data['wins'] / (team_data['wins'] + team_data['losses']) if (team_data['wins'] + team_data['losses']) > 0 else 0
        
        opponents = [opp for _, opp in remaining_schedule[team_id]]
        sos = sum(teams[opp]['wins'] / (teams[opp]['wins'] + teams[opp]['losses']) 
                  for opp in opponents if (teams[opp]['wins'] + teams[opp]['losses']) > 0) / len(opponents) if opponents else 0
        
        rpi_scores[team_id] = round((team_wp * 0.25) + (sos * 0.75), 4)
        sos_scores[team_id] = round(sos, 4)
    
    conn.close()
    return rpi_scores, sos_scores

def update_sos_in_db(sos_scores):
    conn = get_db_connection()
    c = conn.cursor()
    
    for team_id, sos in sos_scores.items():
        c.execute('UPDATE teams SET sos = ? WHERE id = ?', (sos, team_id))
    
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
    sos_values = list(sos_scores.values())
    lapf_values = list(lapf_scores.values())
    avg_lapf = sum(lapf_values) / len(lapf_values) if lapf_values else 0
    max_lapf = max(lapf_values) if lapf_values else 0
    max_points_for = max(team['points_for'] for team in teams) if teams else 0
    
    # Calculate SOS ranks
    sos_ranks = {team_id: rank for rank, (team_id, _) in enumerate(sorted(sos_scores.items(), key=lambda x: x[1], reverse=True), 1)}
    
    # Initialize conference standings
    conference_standings = {}
    
    # First pass: calculate projected wins for all teams and populate conference standings
    for team in teams:
        team_dict = dict(team)
        team_id = team_dict['id']
        conference = team_dict['conference']
        
        if conference not in conference_standings:
            conference_standings[conference] = []
        
        lapf = lapf_scores.get(team_id, 0)
        sos = sos_scores.get(team_id, 0)
        sos_category = categorize_sos(sos, sos_values)
        remaining_games = 17 - (team_dict['wins'] + team_dict['losses'])
        projected_wins = calculate_projected_wins(team_dict['wins'], remaining_games, lapf, avg_lapf, sos_category)
        
        conference_standings[conference].append({
            'id': team_id,
            'projected_wins': projected_wins,
            'points_for': team_dict['points_for']
        })
    
    # Sort conference standings
    for conf in conference_standings:
        conference_standings[conf] = sorted(conference_standings[conf], 
                                            key=lambda x: (x['projected_wins'], x['points_for']), 
                                            reverse=True)
    
    # Second pass: calculate playoff chances, M.O.N.K.E. scores, and prepare final team list
    for team in teams:
        team_dict = dict(team)
        team_id = team_dict['id']
        
        lapf = lapf_scores.get(team_id, 0)
        team_dict['luck_adjusted_points_for'] = round(lapf, 2)
        
        sos = sos_scores.get(team_id, 0)
        sos_category = categorize_sos(sos, sos_values)
        team_dict['strength_of_schedule'] = sos_category
        
        remaining_games = 17 - (team_dict['wins'] + team_dict['losses'])
        projected_wins = calculate_projected_wins(team_dict['wins'], remaining_games, lapf, avg_lapf, sos_category)
        team_dict['projected_wins'] = projected_wins
        
        playoff_chance = calculate_playoff_chance(projected_wins, team_dict['conference'], lapf, avg_lapf, sos_category, conference_standings, team_id)
        team_dict['playoff_chance'] = round(playoff_chance, 1)
        
        monke_score = calculate_monke_score(team_dict, max_lapf, max_points_for, sos_ranks, len(teams))
        team_dict['monke_score'] = monke_score
        
        teams_list.append(team_dict)
    
    # Sort teams by M.O.N.K.E. score
    teams_list.sort(key=lambda x: x['monke_score'], reverse=True)
    
    conn.close()
    return jsonify(teams_list)

def categorize_sos(sos_value, sos_values):
    quartiles = np.percentile(sos_values, [25, 50, 75])
    if sos_value < quartiles[0]:
        return "Easy"
    elif sos_value < quartiles[1]:
        return "Normal"
    elif sos_value < quartiles[2]:
        return "Difficult"
    else:
        return "Very Difficult"

def calculate_projected_wins(current_wins, remaining_games, team_lapf, avg_lapf, sos_category):
    sos_adjustment = {
        "Easy": 0.1,
        "Normal": 0,
        "Difficult": -0.05,
        "Very Difficult": -0.1
    }
    
    projected_wins = current_wins + (remaining_games / 2) * (team_lapf / avg_lapf) * (1 + sos_adjustment[sos_category])
    return round(projected_wins, 1)

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
    
    # Get all teams with their points_for and points_against
    c.execute('SELECT id, points_for, points_against FROM teams')
    teams = c.fetchall()
    
    # Calculate the average points_against across all teams
    total_pa = sum(team['points_against'] for team in teams)
    avg_pa = total_pa / len(teams)
    
    lapf_scores = {}
    
    for team in teams:
        # Calculate LAPF: 80% of points_for + 20% of average points_against
        lapf = (0.8 * team['points_for']) + (0.2 * avg_pa)
        lapf_scores[team['id']] = round(lapf, 2)
    
    conn.close()
    return lapf_scores

# Global variable to store LAPF scores
lapf_scores = {}

def update_lapf_scores():
    global lapf_scores
    lapf_scores = calculate_lapf_for_all_teams()

def get_remaining_schedule():
    current_week = get_current_week()
    remaining_schedule = defaultdict(list)

    for week in range(current_week, 15):  # Assuming a 14-week regular season
        schedule_url = f"https://api.sleeper.app/v1/league/{LEAGUE_ID}/matchups/{week}"
        schedule_response = requests.get(schedule_url)
        if schedule_response.status_code == 200:
            matchups = schedule_response.json()
            matchup_pairs = defaultdict(list)
            
            # Group teams by matchup_id
            for matchup in matchups:
                matchup_pairs[matchup['matchup_id']].append(matchup['roster_id'])
            
            # Assign opponents
            for pair in matchup_pairs.values():
                if len(pair) == 2:
                    remaining_schedule[pair[0]].append((week, pair[1]))
                    remaining_schedule[pair[1]].append((week, pair[0]))

    return remaining_schedule

def get_current_week():
    league_url = f"https://api.sleeper.app/v1/league/{LEAGUE_ID}"
    league_response = requests.get(league_url)
    if league_response.status_code == 200:
        league_data = league_response.json()
        return league_data.get('settings', {}).get('current_week', 1)
    return 1

@app.route('/remaining_schedules')
def display_remaining_schedules():
    conn = get_db_connection()
    c = conn.cursor()
    
    c.execute('SELECT id, name FROM teams')
    teams = c.fetchall()
    conn.close()

    team_dict = {team['id']: team['name'] for team in teams}
    remaining_schedule = get_remaining_schedule()

    # Select 3 random teams
    selected_teams = random.sample(list(team_dict.keys()), 3)

    schedules_text = ""
    for team_id in selected_teams:
        schedules_text += f"Remaining schedule for {team_dict[team_id]} (ID: {team_id}):\n"
        for week, opponent_id in remaining_schedule[team_id]:
            schedules_text += f"  Week {week}: vs {team_dict.get(opponent_id, f'Unknown (ID: {opponent_id})')}\n"
        schedules_text += "\n"

    return render_template('remaining_schedules.html', schedules_text=schedules_text)

def calculate_playoff_chance(projected_wins, conference, lapf, avg_lapf, sos_category, conference_standings, team_id):
    baseline = (projected_wins / 17) * 100
    
    # Conference adjustment
    if conference in conference_standings and conference_standings[conference]:
        conf_adjustment = 20 if conference_standings[conference][0]['id'] == team_id else -10
    else:
        conf_adjustment = 0  # Default adjustment if conference is unknown or empty
    
    # LAPF adjustment
    lapf_adjustment = ((lapf - avg_lapf) / avg_lapf) * 20
    
    # SOS adjustment
    sos_adjustment = {
        "Easy": 5,
        "Normal": 0,
        "Difficult": -5,
        "Very Difficult": -10
    }[sos_category]
    
    playoff_chance = baseline + conf_adjustment + lapf_adjustment + sos_adjustment
    return max(min(playoff_chance, 99.9), 0.1)  # Clamp between 0.1% and 99.9%

def calculate_monke_score(team_dict, max_lapf, max_points_for, sos_ranks, total_teams):
    win_percentage = (team_dict['wins'] / (team_dict['wins'] + team_dict['losses'])) * 100 if (team_dict['wins'] + team_dict['losses']) > 0 else 0
    lapf_score = (team_dict['luck_adjusted_points_for'] / max_lapf) * 100 if max_lapf > 0 else 0
    projected_wins_score = (team_dict['projected_wins'] / 17) * 100
    playoff_chance_score = team_dict['playoff_chance']
    points_for_score = (team_dict['points_for'] / max_points_for) * 100 if max_points_for > 0 else 0
    sos_score = 100 - ((sos_ranks[team_dict['id']] - 1) / (total_teams - 1)) * 100 if total_teams > 1 else 50

    monke_score = (0.25 * win_percentage) + \
                  (0.25 * lapf_score) + \
                  (0.20 * projected_wins_score) + \
                  (0.15 * playoff_chance_score) + \
                  (0.10 * points_for_score) + \
                  (0.05 * sos_score)

    return round(monke_score, 2)

if __name__ == '__main__':
    init_db()
    scheduler = BackgroundScheduler()
    scheduler.add_job(update_data, 'interval', hours=1)
    scheduler.start()
    update_data()  # Run once at startup
    update_lapf_scores()  # Calculate LAPF scores when the app starts
    app.run(debug=True, port=8000)  # Change 8080 to your desired port number
