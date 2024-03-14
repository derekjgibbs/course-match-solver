# Copyright (c) Streamlit Inc. (2018-2022) Snowflake Inc. (2022)
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from urllib.error import URLError

import altair as alt
import pandas as pd
import numpy as np
import streamlit as st
from pulp import LpMaximize, LpProblem, LpVariable, lpSum
from streamlit.hello.utils import show_code
from streamlit_gsheets import GSheetsConnection

url = "https://docs.google.com/spreadsheets/d/1Nl4ipBofunJV-328R1UZx1FWeHHpAtAIrbhBvwjsGBY/edit?usp=sharing"
conn = st.connection("gsheets", type=GSheetsConnection)

course_data = conn.read(spreadsheet=url, ttl=0)

# Initialize 'Utility' column with zeros if it doesn't exist
if 'Utility' not in course_data.columns:
    course_data['Utility'] = 0.0

st.dataframe(course_data)

# User Input
credit_limit = 5.25 # Will replace this with user input
credit_limit = st.number_input("Enter your credit limit", min_value=0.0, max_value=7.0, value=4.0, step=0.25, format="%.2f")

budget = 4400  # For a first-year student
student_year = st.selectbox("Select your year", options=["1st Year", "2nd Year"])
budget = 4400 if student_year == "1st Year" else 5500  # Adjust based on the selected year

# Initialize the ILP problem
problem = LpProblem("Course_Scheduler", LpMaximize)

# Identify class conflicts
def conflicts(course_a, course_b):
    # Check if the time slots overlap
    if course_a['Time'] != course_b['Time']:
        return False

    # Check if the courses are in the same term or if one is in a semester that overlaps the other's quarter
    if course_a['Term'] != course_b['Term']:
        if not ((course_a['Term'] == 'Full' and course_b['Term'] in ['Q1', 'Q2', 'Q3', 'Q4']) or
                (course_b['Term'] == 'Full' and course_a['Term'] in ['Q1', 'Q2', 'Q3', 'Q4'])):
            return False

    # Check for day conflicts (M, W, MW, T, R, TR)
    days_a = set(course_a['Days'])
    days_b = set(course_b['Days'])

    # Monday and Wednesday
    if ('M' in days_a and 'M' in days_b) or ('W' in days_a and 'W' in days_b):
        return True
    if 'MW' in days_a and ('M' in days_b or 'W' in days_b):
        return True
    if 'MW' in days_b and ('M' in days_a or 'W' in days_a):
        return True

    # Tuesday and Thursday
    if ('T' in days_a and 'T' in days_b) or ('R' in days_a and 'R' in days_b):
        return True
    if 'TR' in days_a and ('T' in days_b or 'R' in days_b):
        return True
    if 'TR' in days_b and ('T' in days_a or 'R' in days_a):
        return True

    return False


# Define binary variables for each course section
course_vars = {row['SectionID']: LpVariable(f"x_{row['SectionID']}", cat='Binary') for index, row in course_data.iterrows()}

# Objective function: Maximize the sum of utilities times credits for selected courses
problem += lpSum([row['Utility'] * row['Credits'] * course_vars[row['SectionID']] for index, row in course_data.iterrows()])

# Constraints
# 1. Budget constraint: Sum of prices for selected courses must not exceed the budget
# Placeholder budget (will be determined by the student's year)
problem += lpSum([row['Price'] * course_vars[row['SectionID']] for index, row in course_data.iterrows()]) <= budget, "BudgetConstraint"

# Additional constraints like time slot conflicts and credit limits will be added similarly
# 2. Conflicts constraint: Classes cannot be at the same time
for i, course_a in course_data.iterrows():
    for j, course_b in course_data.iterrows():
        if i >= j:  # Avoid duplicate pairs and self-comparison
            continue
        if conflicts(course_a, course_b):
            problem += course_vars[course_a['SectionID']] + course_vars[course_b['SectionID']] <= 1, f"Conflict_{i}_{j}"

# 3. General section constraints
# Create a dictionary where each key is a course (Section) and each value is a list of section variables for that course
course_sections = {}
for index, row in course_data.iterrows():
    course_name = row['Section']  # Using 'Section' to identify the course
    if course_name not in course_sections:
        course_sections[course_name] = []
    course_sections[course_name].append(course_vars[row['SectionID']])

# Add constraints such that for each course, at most one of its sections can be selected
for course_name, sections in course_sections.items():
    problem += lpSum(sections) <= 1, f"OneSectionPerCourse_{course_name}"

# 4. "One-off" section constraints
# Define a list of lists where each sublist contains mutually exclusive courses
exclusive_courses = [
    ['MGMT6110', 'MGMT6120'],  # Only one of these can be selected
    ['COURSE_X1', 'COURSE_X2'],  # Another set of exclusive courses
    # Add more as needed
]

# Iterate over the exclusive courses and add a constraint for each
for course_group in exclusive_courses:
    course_group_vars = []
    for course in course_group:
        course_group_vars.extend([course_vars[row['SectionID']] for index, row in course_data.iterrows() if row['Section'] == course])
    problem += lpSum(course_group_vars) <= 1, f"ExclusiveConstraint_{'_'.join(course_group)}"

# 4. Credit limit
problem += lpSum([row['Credits'] * course_vars[row['SectionID']] for index, row in course_data.iterrows()]) <= credit_limit, "CreditLimitConstraint"

# Solve the problem
problem.solve()

# Output some results for illustration
selected_courses = [row['SectionID'] for index, row in course_data.iterrows() if course_vars[row['SectionID']].varValue == 1]
selected_courses_total_credits = sum([row['Credits'] for index, row in course_data.iterrows() if row['SectionID'] in selected_courses])
selected_courses_total_utility = sum([row['Utility'] for index, row in course_data.iterrows() if row['SectionID'] in selected_courses])

# Extracting the selected courses
selected_courses = [row['SectionID'] for index, row in course_data.iterrows() if course_vars[row['SectionID']].varValue == 1]

# Constructing the DataFrame for selected courses
selected_courses_data = course_data[course_data['SectionID'].isin(selected_courses)].copy()

# Calculating the total price, utility, and credits
total_price = selected_courses_data['Price'].sum()
total_utility = selected_courses_data['Utility'].sum()
total_credits = selected_courses_data['Credits'].sum()

# Calculate the weighted utility for each selected course
selected_courses_data['Weighted Utility'] = selected_courses_data['Utility'] * selected_courses_data['Credits']

# Construct the summary data with the sum of the price, weighted utility, and credits
summary_data = {
    'SectionID': 'Total',
    'Course Name': '',
    'Instructor': '',
    'Days': '',
    'Time': '',
    'Price': selected_courses_data['Price'].sum(),
    'Utility': '',  # We will not display the raw utility sum in the summary
    'Credits': selected_courses_data['Credits'].sum(),
    'Weighted Utility': selected_courses_data['Weighted Utility'].sum()
}

# Append the summary row to the DataFrame
selected_courses_data = selected_courses_data.append(summary_data, ignore_index=True)

# Adjust the columns to display the weighted utility
selected_courses_data = selected_courses_data[['SectionID', 'Course_Name', 'Instructor', 'Days', 'Time', 'Price', 'Credits', 'Weighted Utility']]

# Display the DataFrame
selected_courses_data



















