from resources.scrapers import scrapers
import urllib2
import os.path
import xbmc
import xbmcaddon

def is_number(s):
    try:
        float(s)
        return True
    except ValueError:
        pass
 
    try:
        import unicodedata
        unicodedata.numeric(s)
        return True
    except (TypeError, ValueError):
        pass
 
    return False

def isThatSxxExx (string):
	if (len(string) != 6):
		return False
	else:
		if (string[0].isdigit() == True):
			return False
		elif (string[1].isdigit() == False):
			return False
		elif(string[2].isdigit() == False):
			return False
		elif (string[3].isdigit() == True):
			return False
		elif (string[4].isdigit() == False):
			return False
		elif (string[5].isdigit() == False):
			return False
		else:
			return True

def extract(text, startText, endText):
    start=text.find(startText,0)
    if start!=-1:
        start=start+startText.__len__()
        end=text.find(endText,start+1)
        if end!=-1:
            return text[start:end]
    return None

def extractAll(text, startText, endText):
    result = []
    start = 0
    pos = text.find(startText, start)
    while pos != -1:
        start = pos + startText.__len__()
        end = text.find(endText, start)
        result.append(text[start:end].replace('\n', '').replace('\t', '').lstrip())
        pos = text.find(startText, end)
    return result

def getEpisodeandSeason (SxxExx):
	string = list(SxxExx)
	Season = int(string[1])*10 + int(string[2])
	Episode = int(string[4])*10 + int(string[5])
	SeasonEpisode = [Season, Episode]
	return SeasonEpisode

def getRealNames (title):
	change = True
	strDummy = title
	strDummy = title.replace(".", " ")
	returnedTitle = ''		
	listString = strDummy.split()
	ShowName = '' 		
	SxxExx = '' 		
	for i in listString:
		if (change == True):
			if (isThatSxxExx(i) == True):
				change = False
				ShowName = returnedTitle
				SxxExx = i
			returnedTitle = returnedTitle + i + ' '
			
	names = [ShowName, SxxExx, returnedTitle]		
	return names	

def isvalid (title):
    checkstring = title
    if (checkstring.find('.srt') != -1):
        return False
    if (checkstring.find('.png') != -1):
        return False
    if (checkstring.find('.jpg') != -1):
        return False
    if (checkstring.find('.png') != -1):
        return False
    if (checkstring.find('.txt') != -1):
        return False
    if (checkstring.find('.nfo') != -1):
        return False
    return True


def textDB (Showname):
    __addon__       = xbmcaddon.Addon(id='plugin.video.torrenter')
    __addonprofile__= xbmc.translatePath(__addon__.getAddonInfo('profile')).decode('utf-8')
    filename = __addonprofile__ + Showname+".txt"
    if os.path.exists(filename) == False:
        show_file = open(filename, "w")
        showstr = Showname.replace(" ", "+")
        url = "http://thetvdb.com/api/GetSeries.php?seriesname="
        url = url+showstr
        response = urllib2.urlopen(url)
        content = response.read()
        id = extract(content, '<seriesid>', '</seriesid>')
        urln = "http://thetvdb.com/api/CEE06027D4C29B06/series/"+str(id)+"/all/he.xml"
        responsen = urllib2.urlopen(urln)
        contentn = responsen.read()
        show_file.write(contentn)

    show_file = open(filename, 'r')
    database = show_file.read()
    show_file.close() 
    return database

def getInfo (seriesname):
    checkstring = seriesname
    name = seriesname
    plot = 'none'
    aired = 'none'
    thumbnail = ''
    Anames = getRealNames(seriesname)
    if isvalid(seriesname) == True:
        if isThatSxxExx(Anames[1]) == True:
            contentn = textDB(Anames[0])
            paragraphs = extractAll(contentn, '<Episode>', '</Episode>')
            SeasonEpisode = getEpisodeandSeason(Anames[1])
            SeasonNumber = str(SeasonEpisode[0])
            EpisodeNumber = str(SeasonEpisode[1])
            EpisodeStart = '<Combined_episodenumber>'
            EpisodeEnd = '</Combined_episodenumber>'
            SeasonStart = '<Combined_season>'
            SeasonEnd = '</Combined_season>'
            episodeoptionone = EpisodeStart+EpisodeNumber+EpisodeEnd
            episodeoptiontwo = EpisodeStart+EpisodeNumber+'.0'+EpisodeEnd
            for i in paragraphs:
                if episodeoptionone in i or episodeoptiontwo in i: 
                    if SeasonStart+SeasonNumber+SeasonEnd in i:
                        plot = extract(i, '<Overview>', '</Overview>')
                        plot = plot.replace("&quot;", '"')
                        name = Anames[1]+" "+extract(i, '<EpisodeName>', '</EpisodeName>')
                        thumbnail = 'http://thetvdb.com/banners/'+extract(i, '<filename>', '</filename>')
			
    info = [name, plot, thumbnail]
    return info
