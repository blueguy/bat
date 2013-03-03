#!/usr/bin/python

## Binary Analysis Tool
## Copyright 2012-2013 Armijn Hemel for Tjaldur Software Governance Solutions
## Licensed under Apache 2.0, see LICENSE file for details

'''
This is a plugin for the Binary Analysis Tool. It generates HTML files for the
following:

* unique strings that were matched, with links to pretty printed source code,
which can be displayed in the BAT GUI.

This should be run as a postrun scan
'''

import os, os.path, sys, gzip, cgi, cPickle

## helper function to condense version numbers and squash numbers.
def squash_versions(versions):
	if len(versions) <= 3:
		versionline = reduce(lambda x, y: x + ", " + y, versions)
		return versionline
	# check if we have versions without '.'
	if len(filter(lambda x: '.' not in x, versions)) != 0:
		versionline = reduce(lambda x, y: x + ", " + y, versions)
		return versionline
	versionparts = []
	# get the major version number first
	majorv = list(set(map(lambda x: x.split('.')[0], versions)))
	for m in majorv:
		maxconsolidationlevel = 0
		## determine how many subcomponents we have at max
		filterversions = filter(lambda x: x.startswith(m + "."), versions)
		if len(filterversions) == 1:
			versionparts.append(reduce(lambda x, y: x + ", " + y, filterversions))
			continue
		minversionsplits = min(list(set(map(lambda x: len(x.split('.')), filterversions)))) - 1
		## split with a maximum of minversionsplits splits
		splits = map(lambda x: x.split('.', minversionsplits), filterversions)
		for c in range(0, minversionsplits):
			if len(list(set(map(lambda x: x[c], splits)))) == 1:
				maxconsolidationlevel = maxconsolidationlevel + 1
			else: break
		if minversionsplits != maxconsolidationlevel:
			splits = map(lambda x: x.split('.', maxconsolidationlevel), filterversions)
		versionpart = reduce(lambda x, y: x + "." + y, splits[0][:maxconsolidationlevel]) + ".{" + reduce(lambda x, y: x + ", " + y, map(lambda x: x[-1], splits)) + "}"
		versionparts.append(versionpart)
	versionline = reduce(lambda x, y: x + ", " + y, versionparts)
	return versionline

def generateHTML(filename, unpackreport, scantempdir, topleveldir, envvars={}):
	if not unpackreport.has_key('sha256'):
		return
	if not unpackreport.has_key('tags'):
		return
	else:
		if not 'ranking' in unpackreport['tags']:
			return
	scanenv = os.environ.copy()
	if envvars != None:
		for en in envvars.split(':'):
			try:
				(envname, envvalue) = en.split('=')
				scanenv[envname] = envvalue
			except Exception, e:
				pass

	reportdir = scanenv.get('BAT_REPORTDIR', '.')
	try:
		os.stat(reportdir)
	except:
		## BAT_REPORTDIR does not exist
		try:
			os.makedirs(reportdir)
		except Exception, e:
			return

	filehash = unpackreport['sha256']

	leaf_file = open(os.path.join(topleveldir, "filereports", "%s-filereport.pickle" % filehash), 'rb')
	leafreports = cPickle.load(leaf_file)
	leaf_file.close()

	if leafreports.has_key('ranking') :
		## the ranking result is (res, dynamicRes, variablepvs)
		(res, dynamicRes, variablepvs) = leafreports['ranking']
	
		if variablepvs == {} and dynamicRes == {}:
			return

		if dynamicRes != {}:
			header = "<html><body>"
			html = ""
			if dynamicRes.has_key('uniquepackages'):
				if dynamicRes['uniquepackages'] != {}:
					html += "<h1>Unique function name matches per package</h1><p><ul>\n"
					ukeys = map(lambda x: (x[0], len(x[1])), dynamicRes['uniquepackages'].items())
					ukeys.sort(key=lambda x: x[1], reverse=True)
					for i in ukeys:
						html += "<li><a href=\"#%s\">%s (%d)</a>" % (i[0], i[0], i[1])
					html += "</ul></p>"
					for i in ukeys:
						html += "<hr><h2><a name=\"%s\" href=\"#%s\">Matches for %s (%d)</a></h2><p>\n" % (i[0], i[0], i[0], i[1])
						upkgs = dynamicRes['uniquepackages'][i[0]]
						upkgs.sort()
						for v in upkgs:
							html += "%s<br>\n" % v
						html += "</p>\n"
			footer = "</body></html>"
			if html != "":
				html = header + html + footer
				nameshtmlfile = gzip.open("%s/%s-functionnames.html.gz" % (reportdir, unpackreport['sha256']), 'wb')
				nameshtmlfile.write(html)
				nameshtmlfile.close()
		if variablepvs != {}:
			header = "<html><body>"
			html = ""
			language = variablepvs['language']

			if language == 'Java':
				fieldspackages = {}
				sourcespackages = {}
				classespackages = {}
				fieldscount = {}
				sourcescount = {}
				classescount = {}
				for i in ['classes', 'sources', 'fields']:
					if not variablepvs.has_key(i):
						continue
					packages = {}
					packagecount = {}
					if variablepvs[i] != []:
						for c in variablepvs[i]:
							lenres = len(list(set(map(lambda x: x[0], variablepvs[i][c]))))
							if lenres == 1:
								pvs = variablepvs[i][c]
								(package,version) = variablepvs[i][c][0]
								if packagecount.has_key(package):
									packagecount[package] = packagecount[package] + 1
								else:
									packagecount[package] = 1
								'''
								## for later use
								for p in pvs:
									(package,version) = p
									if packages.has_key(package):
										packages[package].append(version)
									else:
										packages[package] = [version]
								'''
					if packagecount != {}:
						if i == 'classes':
							classescount = packagecount
						if i == 'sources':
							sourcescount = packagecount
						if i == 'fields':
							fieldscount = packagecount
	
					if packages != {}:
						if i == 'classes':
							classespackages = packages
						if i == 'sources':
							sourcespackages = packages
						if i == 'fields':
							fieldspackages = packages
	
				if classescount != {}:
					html = html + "<h3>Unique matches of class names</h3>\n<table>\n"
					html = html + "<tr><td><b>Name</b></td><td><b>Unique matches</b></td></tr>"
					for i in classescount:
						html = html + "<tr><td>%s</td><td>%d</td></tr>\n" % (i, classescount[i])
					html = html + "</table>\n"
	
				if sourcescount != {}:
					html = html + "<h3>Unique matches of source file names</h3>\n<table>\n"
					html = html + "<tr><td><b>Name</b></td><td><b>Unique matches</b></td></tr>"
					for i in sourcescount:
						html = html + "<tr><td>%s</td><td>%d</td></tr>\n" % (i, sourcescount[i])
					html = html + "</table>\n"
	
				if fieldscount != {}:
					html = html + "<h3>Unique matches of field names</h3>\n<table>\n"
					html = html + "<tr><td><b>Name</b></td><td><b>Unique matches</b></td></tr>"
					for i in fieldscount:
						html = html + "<tr><td>%s</td><td>%d</td></tr>\n" % (i, fieldscount[i])
					html = html + "</table>\n"
	
			if language == 'C':
				if variablepvs.has_key('variables'):
					packages = {}
					packagecount = {}
					## for each variable name determine in how many packages it can be found.
					## Only the unique packages are reported.
					for c in variablepvs['variables']:
						lenres = len(variablepvs['variables'][c])
						if lenres == 1:
							pvs = variablepvs['variables'][c]
							package = variablepvs['variables'][c].keys()[0]
							if packagecount.has_key(package):
								packagecount[package] = packagecount[package] + 1
							else:
								packagecount[package] = 1
								
						'''
						## for later use
						for p in pvs:
							(package,version) = p
							if packages.has_key(package):
								packages[package].append(version)
							else:
								packages[package] = [version]
						'''
	
					if packagecount != {}:
						html = html + "<h3>Unique matches of variables</h3>\n<table>\n"
						html = html + "<tr><td><b>Name</b></td><td><b>Unique matches</b></td></tr>"
						for i in packagecount:
							html = html + "<tr><td>%s</td><td>%d</td></tr>\n" % (i, packagecount[i])
						html = html + "</table>\n"
	
			footer = "</body></html>"
			if html != "":
				html = header + html + footer
				nameshtmlfile = gzip.open("%s/%s-names.html.gz" % (reportdir, unpackreport['sha256']), 'wb')
				nameshtmlfile.write(html)
				nameshtmlfile.close()
