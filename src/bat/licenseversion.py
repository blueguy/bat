#!/usr/bin/python

## Binary Analysis Tool
## Copyright 2013 Armijn Hemel for Tjaldur Software Governance Solutions
## Licensed under Apache 2.0, see LICENSE file for details

import os, os.path, sys, subprocess, copy, cPickle, multiprocessing, sqlite3

'''
This program can be used to optionally prune results of a scan. Sometimes
results of scans can get very large, for example a scan of a Linux kernel image
could have thousands of string matches, which can each be found in a few
hundred kernel source code archives.

By pruning results the amount of noise can be much reduce, reports can be made
smaller and source code checks using the results of BAT can be made more
efficient.

To remove a version A from the set of versions the following conditions have
to hold:

* there is a minimum amount of results available (20 or 30 seems a good cut off value)

* all strings/variables/function names found in A are found in the most promising
version

* the amount of strings/variables/function names found in A are significantly
smaller than the amount in the most promising version (expressed as a maximum
percentage)
'''

def prune(scanenv, uniques, package):
	if not scanenv.has_key('BAT_KEEP_VERSIONS'):
		## keep all versions
		return uniques
	else:
		keepversions = int(scanenv.get('BAT_KEEP_VERSIONS', 0))
		if keepversions <= 0:
			## keep all versions
			return uniques

	## there need to be a minimum of unique hits (like strings), otherwise
	## it's silly
	if not scanenv.has_key('BAT_MINIMUM_UNIQUE'):
		## keep all versions
		return uniques
	else:
		minimumunique = int(scanenv.get('BAT_MINIMUM_UNIQUE', 0))
		if minimumunique <= 0:
			## keep all versions
			return uniques

	if len(uniques) < minimumunique:
		return uniques

	uniqueversions = {}

	linesperversion = {}

	for u in uniques:
		(line, res) = u
		seenversions = []
		for r in res:
			(sha256, version, linenumber, filename) = r
			if version in seenversions:
				continue
			if linesperversion.has_key(version):
				linesperversion[version].append(line)
			else:
				linesperversion[version] = [line]
			seenversions.append(version)
			if uniqueversions.has_key(version):
				uniqueversions[version] += 1
			else:
				uniqueversions[version] = 1
	if len(uniqueversions.keys()) == 1:
		return uniques

	pruneme = []

	unique_sorted_rev = sorted(uniqueversions, key = lambda x: uniqueversions.__getitem__(x), reverse=True)
	unique_sorted = sorted(uniqueversions, key = lambda x: uniqueversions.__getitem__(x))

	for l in unique_sorted_rev:
		if l in pruneme:
			continue
		for k in unique_sorted:
			if uniqueversions[k] == uniqueversions[l]:
				continue
			if uniqueversions[k] > uniqueversions[l]:
				break
			if k in pruneme:
				continue
			if l == k:
				continue
			inter = set(linesperversion[l]).intersection(set(linesperversion[k]))
			if list(set(linesperversion[k]).difference(inter)) == []:
				pruneme.append(k)

	notpruned = list(set(uniqueversions.keys()).difference(set(pruneme)))
	newuniques = []
	for u in uniques:
		(line, res) = u
		newres = []
		for r in res:
			(sha256, version, linenumber, filename) = r
			if version in notpruned:
				newres.append(r)
		if newres != []:
			newuniques.append((line, newres))
	return newuniques

def determinelicense_version_copyright(unpackreports, scantempdir, topleveldir, debug=False, envvars=None):
	scanenv = os.environ.copy()
	envvars = licensesetup(envvars, debug)
	if envvars != []:
		for en in envvars[1].items():
			try:
				(envname, envvalue) = en
				scanenv[envname] = envvalue
			except Exception, e:
				pass

	determineversion = False
	if scanenv.get('BAT_RANKING_VERSION', 0) == '1':
		determineversion = True

	determinelicense = False
	if scanenv.get('BAT_RANKING_LICENSE', 0) == '1':
		determinelicense = True
		#licenseconn = sqlite3.connect(scanenv.get('BAT_LICENSE_DB'))
		#licensecursor = licenseconn.cursor()

	determinecopyright = False
	if scanenv.get('BAT_RANKING_COPYRIGHT', 0) == '1':
		determinecopyright = True
		#copyrightconn = sqlite3.connect(scanenv.get('BAT_LICENSE_DB'))
		#copyrightcursor = copyrightconn.cursor()

	## only continue if there actually is a need
	if not determinelicense and not determineversion and not determinecopyright:
		#c.close()
		#conn.close()
		return None

	## now read the pickles
	rankingfiles = []

	## ignore files which don't have ranking results
	filehashseen = []
	for i in unpackreports:
		if not unpackreports[i].has_key('sha256'):
			continue
		if not unpackreports[i].has_key('tags'):
			continue
		if not 'ranking' in unpackreports[i]['tags']:
			continue
		filehash = unpackreports[i]['sha256']
		if filehash in filehashseen:
			continue
		filehashseen.append(filehash)
		if not os.path.exists(os.path.join(topleveldir, "filereports", "%s-filereport.pickle" % filehash)):
			continue
		rankingfiles.append((scanenv, unpackreports[i], topleveldir, determinelicense, determinecopyright))
	pool = multiprocessing.Pool()
	pool.map(compute_version, rankingfiles)

def compute_version((scanenv, unpackreport, topleveldir, determinelicense, determinecopyright)):
	masterdb = scanenv.get('BAT_DB')

	## open the database containing all the strings that were extracted
	## from source code.
	conn = sqlite3.connect(masterdb)
	## we have byte strings in our database, not utf-8 characters...I hope
	conn.text_factory = str
	c = conn.cursor()

	if determinelicense:
		licenseconn = sqlite3.connect(scanenv.get('BAT_LICENSE_DB'))
		licensecursor = licenseconn.cursor()

	if determinecopyright:
		copyrightconn = sqlite3.connect(scanenv.get('BAT_LICENSE_DB'))
		copyrightcursor = copyrightconn.cursor()

	## keep a list of versions per sha256, since source files could contain more than one license
	seensha256 = []

	## keep a list of versions per sha256, since source files often are in more than one version
	sha256_versions = {}
	newreports = []
	filehash = unpackreport['sha256']
	leaf_file = open(os.path.join(topleveldir, "filereports", "%s-filereport.pickle" % filehash), 'rb')
	leafreports = cPickle.load(leaf_file)
	leaf_file.close()
	if not leafreports.has_key('ranking'):
		return

	(res, dynamicRes, variablepvs) = leafreports['ranking']

	## TODO: fix for if res == None, but dynamicRes is not
	if res == None:
		return
	for r in res['reports']:
		(rank, package, unique, percentage, packageversions, packagelicenses, language) = r
		if unique == []:
			newreports.append(r)
			continue
		newuniques = []
		newpackageversions = {}
		packagecopyrights = []
		countsha256 = []
		for u in unique:
			line = u[0]
			## We should store the version number with the license.
			## There are good reasons for this: files are sometimes collectively
			## relicensed when there is a new release (example: Samba 3.2 relicensed
			## to GPLv3+) so the version number can be very significant for licensing.
			## determinelicense and determinecopyright *always* imply determineversion
			c.execute("select distinct sha256, linenumber, language from extracted_file where programstring=?", (line,))
			versionsha256s = filter(lambda x: x[2] == language, c.fetchall())
			countsha256 = list(set(countsha256 + versionsha256s))

			line_sha256_version = []
			for s in versionsha256s:
				if not sha256_versions.has_key(s[0]):
					c.execute("select distinct version, package, filename from processed_file where sha256=?", (s[0],))
					versions = c.fetchall()
					versions = filter(lambda x: x[1] == package, versions)
					sha256_versions[s[0]] = map(lambda x: (x[0], x[2]), versions)
					for v in versions:
						line_sha256_version.append((s[0], v[0], s[1], v[2]))
				else:
					for v in sha256_versions[s[0]]:
						line_sha256_version.append((s[0], v[0], s[1], v[1]))
			newuniques.append((line, line_sha256_version))

		newuniques = prune(scanenv, newuniques, package)

		for u in newuniques:
			versionsha256s = u[1]
			licensepv = []
			for s in versionsha256s:
				v = s[1]
				if newpackageversions.has_key(v):
					newpackageversions[v] = newpackageversions[v] + 1
				else:   
					newpackageversions[v] = 1
				if determinelicense:
					if not s[0] in seensha256:
						licensecursor.execute("select distinct license, scanner from licenses where sha256=?", (s[0],))
						licenses = licensecursor.fetchall()
						if not len(licenses) == 0:
							#licenses = squashlicenses(licenses)
							licensepv = licensepv + licenses
							#for v in map(lambda x: x[0], licenses):
							#       licensepv.append(v)
						seensha256.append(s[0])
					packagelicenses = list(set(packagelicenses + licensepv))

		## extract copyrights. 'statements' are not very accurate so ignore those for now in favour of URL
		## and e-mail
		if determinecopyright:
			copyrightpv = []
			copyrightcursor.execute("select distinct * from extracted_copyright where sha256=?", (s[0],))
			copyrights = copyrightcursor.fetchall()
			copyrights = filter(lambda x: x[2] != 'statement', copyrights)
			if copyrights != []:
				copyrights = list(set(map(lambda x: (x[1], x[2]), copyrights)))
				copyrightpv = copyrightpv + copyrights
				packagecopyrights = list(set(packagecopyrights + copyrightpv))

		newreports.append((rank, package, newuniques, percentage, newpackageversions, packagelicenses, language))

	## TODO: determine versions of functions and variables here as well

	if dynamicRes.has_key('versionresults'):
		newresults = {}
		for package in dynamicRes['versionresults'].keys():
			uniques = dynamicRes['versionresults'][package]
			newuniques = prune(scanenv, uniques, package)
			newresults[package] = newuniques
		dynamicRes['versionresults'] = newresults

	res['reports'] = newreports

	leaf_file = open(os.path.join(topleveldir, "filereports", "%s-filereport.pickle" % filehash), 'wb')
	leafreports = cPickle.dump(leafreports, leaf_file)
	leaf_file.close()

	## cleanup
	if determinelicense:
		licensecursor.close()
		licenseconn.close()

	if determinecopyright:
		copyrightcursor.close()
		copyrightconn.close()

	c.close()
	conn.close()

## method that makes sure that everything is set up properly and modifies
## the environment, as well as determines whether the scan should be run at
## all.
## Returns tuple (run, envvars)
## * run: boolean indicating whether or not the scan should run
## * envvars: (possibly) modified
## This is the minimum that is needed for determining the licenses
def licensesetup(envvars, debug=False):
	scanenv = os.environ.copy()
	newenv = {}
	if envvars != None:
		for en in envvars.split(':'):
			try:
				(envname, envvalue) = en.split('=')
				scanenv[envname] = envvalue
				newenv[envname] = envvalue
			except Exception, e:
				pass

	## Is the master database defined?
	if not scanenv.has_key('BAT_DB'):
		return (False, None)

	masterdb = scanenv.get('BAT_DB')

	## Does the master database exist?
	if not os.path.exists(masterdb):
		return (False, None)

	## Does the master database have the right tables?
	## processed_file is always needed
	conn = sqlite3.connect(masterdb)
	c = conn.cursor()
	res = c.execute("select * from sqlite_master where type='table' and name='processed_file'").fetchall()
	if res == []:
		c.close()
		conn.close()
		return (False, None)

	## extracted_file is needed for string matches
	res = c.execute("select * from sqlite_master where type='table' and name='extracted_file'").fetchall()
	if res == []:
		stringmatches = False
	else:
		stringmatches = True

	## TODO: copy checks for functions as well

	## check the license database. If it does not exist, or does not have
	## the right schema remove it from the configuration
	if scanenv.get('BAT_RANKING_LICENSE', 0) == '1' or scanenv.get('BAT_RANKING_COPYRIGHT', 0) == 1:
		if scanenv.get('BAT_LICENSE_DB') != None:
			try:
				licenseconn = sqlite3.connect(scanenv.get('BAT_LICENSE_DB'))
				licensecursor = licenseconn.cursor()
				licensecursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='licenses';")
				if licensecursor.fetchall() == []:
					if newenv.has_key('BAT_LICENSE_DB'):
						del newenv['BAT_LICENSE_DB']
					if newenv.has_key('BAT_RANKING_LICENSE'):
						del newenv['BAT_RANKING_LICENSE']
				## also check if copyright information exists
				licensecursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='extracted_copyright';")
				if licensecursor.fetchall() == []:
					if newenv.has_key('BAT_RANKING_COPYRIGHT'):
						del newenv['BAT_RANKING_COPYRIGHT']
				licensecursor.close()
				licenseconn.close()
			except:
				if newenv.has_key('BAT_LICENSE_DB'):
					del newenv['BAT_LICENSE_DB']
				if newenv.has_key('BAT_RANKING_LICENSE'):
					del newenv['BAT_RANKING_LICENSE']
				if newenv.has_key('BAT_RANKING_COPYRIGHT'):
					del newenv['BAT_RANKING_COPYRIGHT']
	## cleanup
	c.close()
	conn.close()
	return (True, newenv)
