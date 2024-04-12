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

student_year = st.selectbox("Select your year", options=["1st Year", "2nd Year"])
budget = 4400 if student_year == "1st Year" else 5500  # Adjust based on the selected year

# Initialize an empty DataFrame to store user inputs if it doesn't already exist in session state
if 'user_utilities' not in st.session_state:
    st.session_state['user_utilities'] = pd.DataFrame(columns=['Course', 'SectionID', 'Utility'])


# Initialize the ILP problem
problem = LpProblem("Course_Scheduler", LpMaximize)

# Define binary variables for each course section
course_vars = {row['SectionID']: LpVariable(f"x_{row['SectionID']}", cat='Binary') for index, row in course_data.iterrows()}

# Objective function: Maximize the sum of utilities times credits for selected courses
problem += lpSum([row['Utility'] * row['Credits'] * course_vars[row['SectionID']] for index, row in course_data.iterrows()])

# Constraints
# 1. Budget constraint: Sum of prices for selected courses must not exceed the budget
problem += lpSum([row['Price'] * course_vars[row['SectionID']] for index, row in course_data.iterrows()]) <= budget, "BudgetConstraint"

# 2. Conflicts constraint: Classes cannot be at the same time

# Function to determine group IDs
def get_group_id(row):
    # Initialize an empty list to hold components of the group ID
    group_components = []
    
    # Add the time slot as the first component
    group_components.append(row['Time'])
    
    # Add term-related components
    if row['Term'] == 'Full':
        # Full semester courses conflict with any quarter course in the same time slot
        group_components.append('Full')
    else:
        # Quarter-specific ID
        group_components.append(row['Term'])
    
    # Add day-related components
    if 'M' in row['Days']:
        group_components.append('M')
    if 'W' in row['Days']:
        group_components.append('W')
    if 'T' in row['Days']:
        group_components.append('T')
    if 'R' in row['Days']:
        group_components.append('R')
    
    # Concatenate all components to form a unique group ID
    return '_'.join(group_components)

# Apply the function to each row to assign group IDs
course_data['GroupID'] = course_data.apply(get_group_id, axis=1)

# Initialize a dictionary to hold the courses for each group
grouped_courses = {}

# Populate the dictionary with courses
for index, row in course_data.iterrows():
    group_id = row['GroupID']
    if group_id not in grouped_courses:
        grouped_courses[group_id] = []
    grouped_courses[group_id].append(course_vars[row['SectionID']])

# Create constraints for each group
for group_id, courses in grouped_courses.items():
    problem += lpSum(courses) <= 1, f"GroupConstraint_{group_id}"

# 3. Section constraint: Cannot be in more than one of the same section
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



















