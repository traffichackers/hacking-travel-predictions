"""This module should read all relevant NCDC weather files for a given site (user-specified), 
traversing the directory for those files and returning a single data-frame containing all 
relevant months."""

import sys
import os
import pandas as pd
import numpy as np
import BlueToadAnalysis as BTA
import math
import urllib2 as url
import BeautifulSoup as SOUP
import json
import datetime as dt

global days_in_months 
global leaps
days_in_months = np.cumsum([31,28,31,30,31,30,31,31,30,31,30,31]) #for date conversion
leaps = [1900 + 4 * x for x in range(50)] #for leap year determination

def GetTimeFromDateTime(now, time = True, d_i_m = days_in_months, ls = leaps):
	"""Given a (now) from datetime.datetime.now, return the standard YYYYDOY.XXX 
	in five-minute fractions..."""
	w_date = now.year * 10000 + now.month * 100 + now.day
	w_time = now.hour * 100 + now.minute + float(now.second)/60
	now_time = ConvertWeatherDate(w_date, w_time, 288, 3, d_i_m = days_in_months, ls = leaps)
	if time: #if we're only returning the fraction of the day (.XXX)
		return round(now_time - int(now_time),3)
	else: #if we want the (YYYYDOY)
		return int(now_time)
		
def GetRelevantFileList(site_name, weather_dir):
	"""Given the (site_name) and the directory to search for files (weather_dir),
	a relative path, return a list of all .txt files containing the site name"""
	return [b for b in os.listdir(weather_dir) if '.txt' in b and site_name in b]
	
def GetNCDC_df(weather_dir, ncdc_file):
	"""Given an NCDC file, open the text file, and return a dataframe"""
	f = open(os.path.join(weather_dir, ncdc_file)).readlines()
	lines_of_data = False #we know the first several lines of the file can be removed
	NCDC_as_dic = {} #blank dictionary
	for line in f: #iterate over the lines of the file
		if 'SkyCondition' in line: #if this is the row of columns
			column_list = line.strip().split(',')
			lines_of_data = True #everything hereafter is viable data
			for c in column_list: #add a key in the dictionary for each attribute
				NCDC_as_dic[c] = [] #empty list, to be appended with each line of data
		elif lines_of_data and len(line) > 1: #if this is a line of data
			split_line = line.strip().split(',')
			for s,c in zip(split_line, column_list): 
				try: #if we can coerce the string to float
					NCDC_as_dic[c].append(float(s))
				except ValueError: #if we cannot, just append the string
					NCDC_as_dic[c].append(s)
	return pd.DataFrame(NCDC_as_dic)

def BuildSiteDataFrame(weather_dir, all_files):
	"""Open each member of (all_files) in (weather_dir) and return one full data frame"""
	for ind, f in enumerate(all_files):
		print "Reading file %d, %s" % (ind, f)
		if ind == 0: #if this is the first file:
			site_df = GetNCDC_df(weather_dir, f)
		else: #add this data frame to the previous one:
			site_df = site_df.append(GetNCDC_df(weather_dir,f))
			site_df.index = range(len(site_df)) #re-index 
	return site_df
	
def GetType(w):
	"""Return a mapped value for numerous types of weather to one heading.
	More information found at: http://cdo.ncdc.noaa.gov/qclcd/qclcddocumentation.pdf."""
	if 'SN' in w or 'FZ' in w: #snow or freezing rain
		return 'SN'
	elif 'RA' in w or 'TS' in w: #various forms of rain
		return 'RA'
	elif 'FG' in w or 'HZ' in w or 'BR' in w: #fog, haze, mist
		return 'FG'
	else:
		return ' ' #clear weather
	
def GetClosestSite(NOAADic, roadway, weather_site_default, w_def):
	if roadway in NOAADic.keys():
		closest_site = NOAADic[roadway]
		if closest_site == weather_site_default: closest_site = w_def #convert to the site in NOAA_df
	else: #if our dictionary does not contain the closest site to...
		closest_site = w_def
	return closest_site
	
def RealTimeWeather(D, NOAADic, NOAA_df, pairs_conds, weights):
	"""Given a dictionary describing which weather site should be used for each roadway (NOAADic), a dictionary of the
	conditions at each pair (pairs_conds), and a third dictionary containing defaul parameters (D), return the generalized
	weather conditions at each site."""
	NOAA_site_conditions = {}
	for roadway in pairs_conds.keys(): #each roadway
		print "Gathering last %d hours of weather information for roadway %s" % (D['traffic_system_memory']/12, roadway)
		closest_site = GetClosestSite(NOAADic, roadway, D['weather_site_default'], D['w_def'])
		index = list(NOAA_df.Location).index(closest_site)
		radio_code = NOAA_df.Code[index] #four letter code used for weather website definition
		if radio_code not in NOAA_site_conditions.keys():
			NOAA_site_conditions = GetHistoricalFromSite(D['WeatherURL_historical'], radio_code, 
										D['traffic_system_memory'], D['weather_cost_facs'], weights, NOAA_site_conditions)
		pairs_conds[roadway][1] = NOAA_site_conditions[radio_code]
	return pairs_conds	
		
def GetHistoricalFromSite(weather_url, radio_code, steps_back, weather_cost_facs, weights, NOAA_site_conditions):
	page = url.urlopen(weather_url + radio_code + ".html")
	parsed_page = SOUP.BeautifulSoup(page)
	table_data = parsed_page.findAll('td')
	days, times, conditions = GetDaysTimesAndConditions(table_data)
	steps_to_most_recent = Get5MinStepsToPreviousTimes(days, times, steps_back)
	prior_weather_conditions = GenerateWeatherSequence(conditions, steps_to_most_recent, steps_back)
	NOAA_site_conditions[radio_code] = BTA.CalculateAntecedentWeather(prior_weather_conditions, weights, weather_cost_facs, steps_back)
	return NOAA_site_conditions
	
def GenerateWeatherSequence(conditions, historical_changeovers, steps_back):
	condition_list = []
	for i in range(steps_back):
		if i <= historical_changeovers[0]:
			condition_list.append(conditions[0])
		else:
			condition_list.append(conditions[GetClosestInList(i, historical_changeovers)])
	return condition_list
	
def GetClosestInList(val, numerical_list):
	for index, item in enumerate(numerical_list):
		if val < item:
			if abs(val-numerical_list[index]) < abs(numerical_list[index-1]-val): 
				return index
			else:
				return index-1
	
def Get5MinStepsToPreviousTimes(days, times, steps_back):
	steps_away_historically = []
	for d, t in zip(days, times):
		steps_away_historically.append(Get5MinStepsToMostRecentTime(d,t))
		if steps_away_historically[-1] > steps_back: return steps_away_historically
	return steps_away_historically
		
def	Get5MinStepsToMostRecentTime(NOAA_day, NOAA_clocktime):
	current_time = dt.datetime.now()
	NOAA_hour, NOAA_minute = [int(t) for t in NOAA_clocktime.split(':')]
	most_recent_NOAA_time = dt.datetime(year = current_time.year, month = current_time.month, day = NOAA_day, 
										hour = NOAA_hour, minute = NOAA_minute)
	if most_recent_NOAA_time.day > current_time.day: 
		if most_recent_NOAA_time.month == 1:
			most_recent_NOAA_time = dt.datetime(year = current_time.year, month = 12, day = NOAA_day, hour = NOAA_hour, minute = NOAA_minute)
		else:
			most_recent_NOAA_time = dt.datetime(year = current_time.year, month = 1, day = NOAA_day, hour = NOAA_hour, minute = NOAA_minute)
	return (current_time - most_recent_NOAA_time).seconds/300
	
def GetDaysTimesAndConditions(td):
	date_value_flag, weather_flag = True, True #are we expecting the next integral value we see to be a date?  Do we have weather info yet?
	days, times, conditions = [], [], []
	first_valid_td_index = GetFirstValid_td_index(td)
	date_time_condition_indices = [(8 + i*18, 9 + i*18, 12 + i*18) for i in range(len(td)/18 - 1)] 
	for d,t,c in date_time_condition_indices:
		days.append(int(td[d].text))
		times.append(td[t].text)
		if ('Snow' in td[c].text or 'Ice' in td[c].text or 'Freezing' in td[c].text): #this all becomes the "SNOW" heading
			conditions.append('SN')
		elif ('Rain' in td[c].text or 'Thunderstorm' in td[c].text): #this all becomes the "RAIN/STORM" heading
			conditions.append('RA')
		elif ('Fog' in td[c].text or 'Haze' in td[c].text or 'Dust' in td[c].text or 'Funnel' in td[c].text or 'Tornado' in td[c].text):
			conditions.append('FG')
		elif ('Fair' in td[c].text or 'Few' in td[c].text or 'Cloud' in td[c].text or 'Unknown' 
			   in td[c].text or 'cast' in td[c].text or 'NA' in td[c].text):
			conditions.append(' ')
	return days, times, conditions		
		
def GetFirstValid_td_index(table_data): 
	for i,td in enumerate(table_data):
		if len(td.text) == 2:
			return i
	
def GetRealTimeFromSite(weather_url, radio_code):
	"""Given a four-letter (radio_code) string for NOAA, return the current weather conditions as one of four classifications
	from the site within the (weather_url) webspace."""
	page = url.urlopen(weather_url + radio_code + ".rss")
	parsed_page = SOUP.BeautifulSoup(page)
	titles = parsed_page.findAll('title') #grab the bullet points from the key page	
	weather_tag = titles[-1] #the last title should contain the weather
	w = weather_tag.contents[0].strip() #contains "Partly Cloudy and 83 F at..."
	if 'Snow' in w or 'Ice' in w or 'Freezing' in w: #this all becomes the "SNOW" heading
		return 'SN'
	elif 'Rain' in w or 'Thunderstorm' in w: #this all becomes the "RAIN/STORM" heading
		return 'RA'
	elif 'Fog' in w or 'Haze' in w or 'Dust' in w or 'Funnel' in w or 'Tornado' in w: #fog, haze, mist, wind...
		return 'FG'
	else:
		return ' ' #clear weather
		
def RoundToNearestNth(val, N, dec):
	"""Given a (val), round to the nearest (N)th fraction to (dec) decimal places,
	for instance, 100.139 to the nearest 20th, to 3 places, is: 100.150."""
	frac = int((val - int(val)) * N + 0.5) 
	return round(int(val) + float(frac)/N, dec)

def ConvertWeatherDate(w_date, w_time, N, dec, d_i_m = days_in_months, ls = leaps):
	"""Convert a (w_date) in YYYYMMDD format and a (w_time) in 0000 (<2400) format
	to a date of YYYYDOY.XXX... to (dec) decimal places rounded to the nearest (N)
	the of a day."""
	year = int(w_date/10000)
	month = int((w_date - 10000 * year)/100)
	day = int((w_date - 10000 * year - 100 * month))
	if month > 2 and year in ls: #if this is a leap year to consider
		day_of_year = d_i_m[month-2] + day
	elif month == 1: #this is January date
		day_of_year = day - 1
	else: #This is a non-January date, that is not impacted by leap years
		day_of_year = d_i_m[month-2] + day - 1 #so Jan 1st is 2012000.XXX, e.g.
	time = RoundToNearestNth((w_time - w_time % 100)/2400 + (w_time % 100)/60/24, N, dec) #get fractional time of day, rounded...
	return int(year * 1000 + day_of_year) + time

def ShortestDist(LatLon_df, Lat, Lon):
	"""Given a (Lat), a (Lon) and a (LatLon_df) containing columns of lats and lons, return the row
	of that data frame corresponding to the site closest to Lat,Lon."""
	distances = [(Lat-x)**2 + (Lon-y)**2 for x,y in zip(LatLon_df.Lat, LatLon_df.Lon)]
	return distances.index(np.min(distances))
	
def GetWSiteName(D, a, RoadwayCoordsDic):
	"""For a given pair_id (a), with the relevant dictionary to store paths (D), either we already
	know which site is closest - this could be a preprocessing step - or we need to search a database
	for the closest weather gauge.  This function will return the closest site as a string bearing its
	name, 'Bedford', e.g."""
	if D['weather_site_name'] != 'closest': #i.e. if this is already filled with a site name
		return D['weather_site_name']
	else: #we need to choose the appropriate NCDC climate gauge
		w_site_coords = pd.read_csv(os.path.join(D['data_path'],"WeatherSite_Coords.csv"))
		if str(a) in RoadwayCoordsDic.keys(): #if these roadways' coordinates are listed
			lat, lon = RoadwayCoordsDic[str(a)]['Lat'], RoadwayCoordsDic[str(a)]['Lon']
			return w_site_coords.Site[ShortestDist(w_site_coords, lat, lon)]
		else:
			return D['weather_site_default']

def BuildClosestNOAADic(NOAA_df, pair_ids, D):
	"""Given a list of (pair_ids), and the name of a dictionary of roadway coordinates (CoordsDic_name), combine with a list of
	NOAA sites and their locations (NOAA_df_name) and write a dictionary to file that contains the closest weather locations for
	real-time weather information for each roadway.  If no coordinates are available, the chosen site should be "XXXXX" and a default
	shall be chosen from (D)."""
	RoadwayCoords = BTA.GetJSON(D['data_path'], D['CoordsDic_name']);
	NOAA_site_dic = {}
	for p in pair_ids:
		NOAA_site_dic[str(p)] = ChooseClosestSite(p, RoadwayCoords, NOAA_df, D) #whichever weather site is closest in Euclidean terms
	with open(os.path.join(D['update_path'], 'ClosestWeatherSite.txt'), 'wb') as outfile:
		json.dump(NOAA_site_dic, outfile)
	return NOAA_site_dic
	
def ChooseClosestSite(roadway, RoadwayCoords, NOAA_df, D):
	"""Given a (roadway), a dictionary (RoadwayCoords) containing the lat/lon of roadways, a dictionary (D) containing the default 
	location to use if the roadway's coordinates are unknown, and a list of NOAA sites and their lat/lon coordinates (NOAA_duf)
	return the closest site in terms of euclidian distance."""
	if str(roadway) not in RoadwayCoords.keys(): #if this roadway does not contain coordinates for use, return the default site	
		return D['weather_site_default']
	else:
		road_lat, road_lon = RoadwayCoords[str(roadway)]['Lat'], RoadwayCoords[str(roadway)]['Lon']
	min_dist = 9999; closest_site = D['weather_site_default']
	for lat, lon, site in zip(NOAA_df.Lat, NOAA_df.Lon, NOAA_df['Location']):
		euclidian_dist = math.sqrt((lat-road_lat)**2 + (lon-road_lon)**2)
		if euclidian_dist < min_dist: #if this is the closest site we've seen
			min_dist = euclidian_dist; closest_site = site
	return closest_site
	
			
def GetWeatherData(weather_dir, site_name):
	"""Given the (site_name) of the relevant weather site ("BostonAirport", e.g.), and the
	(weather_dir) in which they are found, return the full data frame."""
	if os.path.exists(os.path.join(weather_dir, site_name + "_NCDC.csv")):
		return pd.read_csv(os.path.join(weather_dir, site_name + "_NCDC.csv"))
	else: #if the relevant .csv file must be generated (generally a 5-10 second process)
		file_list = GetRelevantFileList(site_name, weather_dir)
		full_site = BuildSiteDataFrame(weather_dir, file_list)
		full_site.to_csv(os.path.join(weather_dir, site_name + "_NCDC.csv"), index = False)
	
if __name__ == "__main__":
	script_name, site_name = sys.argv
	D = BTA.HardCodedParameters()
	weather_dir = D['weather_dir']
	file_list = GetRelevantFileList(site_name, weather_dir)
	full_site = BuildSiteDataFrame(weather_dir, file_list)
	full_site.to_csv(os.path.join(weather_dir, site_name + "_NCDC.csv"), index = False)