#!/usr/bin/python

## Binary Analysis Tool
## Copyright 2015 Armijn Hemel for Tjaldur Software Governance Solutions
## Copyright 2015 Black Duck Software, Inc. All Rights Reserved.
## Licensed under Apache 2.0, see LICENSE file for details

'''
This is a plugin to create JSON output of all results of the Binary Analysis Tool,
including the ranking algorithm.

The documentation of the format can be found in the 'doc' directory (subject to change)
'''

import os, sys, re, json, cPickle, multiprocessing, copy, gzip, codecs
import bat.batdb

def writejson((filehash,topleveldir, outputhash, hashdatabase, batdb, scanenv)):
	batconnection = None
	if batdb != None:
		batconnection = batdb.getConnection(hashdatabase,scanenv)
		if batconnection != None:
			cursor = batconnection.cursor()
	hashcache = {}
	## read the data from the pickle file
	leaf_file = open(os.path.join(topleveldir, "filereports", "%s-filereport.pickle" % filehash), 'rb')
	leafreports = cPickle.load(leaf_file)
	leaf_file.close()
	## then mangle the data and dump it into a JSON file
	jsonreport = {}

	if "tags" in leafreports:
		jsonreport['tags'] = list(set(copy.deepcopy(leafreports['tags'])))
	## now go through all of the scans that are there. This is hardcoded.
	## TODO: make more generic based on configuration.
	for i in ['busybox-version', 'forges', 'licenses']:
		if i in leafreports:
			jsonreport[i] = copy.deepcopy(leafreports[i])

	if outputhash != None and outputhash != 'sha256' and batconnection != None:
		query = batdb.getQuery("select %s from hashconversion where sha256=" % outputhash + "%s")

	## then the 'ranking' scan
	if 'ranking' in leafreports:
		jsonreport['ranking'] = {}
		(stringidentifiers, functionnameresults, variablenameresults, language) = leafreports['ranking']

		## first the language
		jsonreport['ranking']['language'] = language

		## then the string identifier results
		jsonreport['ranking']['stringresults'] = {}
		jsonreport['ranking']['stringresults']['unmatched'] = []
		jsonreport['ranking']['stringresults']['matchednonassignedlines'] = 0
		jsonreport['ranking']['stringresults']['matchednotclonelines'] = 0
		jsonreport['ranking']['stringresults']['nonUniqueMatches'] = []
		jsonreport['ranking']['stringresults']['scores'] = []
		jsonreport['ranking']['stringresults']['reports'] = []
		if stringidentifiers != None:
			if 'unmatched' in stringidentifiers:
				jsonreport['ranking']['stringresults']['unmatched'] = stringidentifiers['unmatched']

			if 'matchednonassignedlines' in stringidentifiers:
				jsonreport['ranking']['stringresults']['matchednonassignedlines'] = stringidentifiers['matchednonassignedlines']
			if 'matchednotclonelines' in stringidentifiers:
				jsonreport['ranking']['stringresults']['matchednotclonelines'] = stringidentifiers['matchednotclonelines']

			if 'nonUniqueMatches' in stringidentifiers:
				jsonreport['ranking']['stringresults']['nonUniqueMatches'] = []
				for u in stringidentifiers['nonUniqueMatches']:
					nonuniquereport = {}
					nonuniquereport['packagename'] = u
					nonuniquereport['nonuniquelines'] = stringidentifiers['nonUniqueMatches'][u]
					jsonreport['ranking']['stringresults']['nonUniqueMatches'].append(nonuniquereport)

			if 'scores' in stringidentifiers:
				jsonreport['ranking']['stringresults']['scores'] = []
				for u in stringidentifiers['scores']:
					scorereport = {}
					scorereport['packagename'] = u
					scorereport['computedscore'] = stringidentifiers['scores'][u]
					jsonreport['ranking']['stringresults']['scores'].append(scorereport)

			if 'reports' in stringidentifiers:
				jsonreport['ranking']['stringresults']['reports'] = []
				for u in stringidentifiers['reports']:
					(rank, package, unique, uniquematcheslen, percentage, packageversions, packagelicenses, packagecopyrights) = u
					report = {}
					report['packagename'] = package
					report['rank'] = rank
					report['percentage'] = percentage
					report['unique'] = []
					for un in unique:
						(identifier, identifierdata) = un
						uniquereport = {}
						uniquereport['identifier'] = identifier
						uniquereport['identifierdata'] = []
						for iddata in identifierdata:
							(filechecksum, linenumber, fileversiondata) = iddata
							identifierdatareport = {}
							if outputhash != None and outputhash != 'sha256' and batconnection != None:
								if filechecksum in hashcache:
									identifierdatareport['filechecksum'] = hashcache[filechecksum]
									identifierdatareport['filechecksumtype'] = outputhash
								else:
									cursor.execute(query, (filechecksum,))
									convertedhash = cursor.fetchone()
									if convertedhash != None:
										hashcache[filechecksum] = convertedhash[0]
										identifierdatareport['filechecksum'] = convertedhash[0]
										identifierdatareport['filechecksumtype'] = outputhash
									else:
										identifierdatareport['filechecksum'] = filechecksum
										identifierdatareport['filechecksumtype'] = 'sha256'
							else:
								identifierdatareport['filechecksum'] = filechecksum
								identifierdatareport['filechecksumtype'] = 'sha256'
							identifierdatareport['linenumber'] = linenumber
							identifierdatareport['packagedata'] = []
							for pack in fileversiondata:
								(packageversion, sourcefilename) = pack
								fileversionreport = {}
								fileversionreport['packageversion'] = packageversion
								fileversionreport['sourcefilename'] = sourcefilename
								identifierdatareport['packagedata'].append(fileversionreport)
							uniquereport['identifierdata'].append(identifierdatareport)
						report['unique'].append(uniquereport)
					report['packageversions'] = []
					for p in packageversions:
						packagereport = {}
						packagereport['packageversion'] = p
						packagereport['packagehits'] = packageversions[p]
						report['packageversions'].append(packagereport)
					jsonreport['ranking']['stringresults']['reports'].append(report)

		## then the functionname results
		jsonreport['ranking']['functionnameresults'] = {}
		jsonreport['ranking']['functionnameresults']['totalfunctionnames'] = 0
		jsonreport['ranking']['functionnameresults']['versionresults'] = []
		if 'totalnames' in functionnameresults:
			jsonreport['ranking']['functionnameresults']['totalfunctionnames'] = functionnameresults['totalnames']
		if 'versionresults' in functionnameresults:
			for packagename in functionnameresults['versionresults']:
				packagereport = {}
				packagereport['packagename'] = packagename
				packagereport['unique'] = []
				for un in functionnameresults['versionresults'][packagename]:
					(identifier, identifierdata) = un
					uniquereport = {}
					uniquereport['identifier'] = identifier
					uniquereport['identifierdata'] = []
					for iddata in identifierdata:
						(filechecksum, linenumber, fileversiondata) = iddata
						identifierdatareport = {}
						if outputhash != None and outputhash != 'sha256':
							if filechecksum in hashcache:
								identifierdatareport['filechecksum'] = hashcache[filechecksum]
								identifierdatareport['filechecksumtype'] = outputhash
							else:
								cursor.execute(query, (filechecksum,))
								convertedhash = cursor.fetchone()
								if convertedhash != None:
									hashcache[filechecksum] = convertedhash[0]
									identifierdatareport['filechecksum'] = convertedhash[0]
									identifierdatareport['filechecksumtype'] = outputhash
								else:
									identifierdatareport['filechecksum'] = filechecksum
									identifierdatareport['filechecksumtype'] = 'sha256'
						else:
							identifierdatareport['filechecksum'] = filechecksum
							identifierdatareport['filechecksumtype'] = 'sha256'
						identifierdatareport['linenumber'] = linenumber
						identifierdatareport['packagedata'] = []
						for pack in fileversiondata:
							(packageversion, sourcefilename) = pack
							fileversionreport = {}
							fileversionreport['packageversion'] = packageversion
							fileversionreport['sourcefilename'] = sourcefilename
							identifierdatareport['packagedata'].append(fileversionreport)
						uniquereport['identifierdata'].append(identifierdatareport)
					packagereport['unique'].append(uniquereport)
				jsonreport['ranking']['functionnameresults']['versionresults'].append(packagereport)

		## then the variablename results
		jsonreport['ranking']['variablenameresults'] = {}
		jsonreport['ranking']['variablenameresults'] = {}
		jsonreport['ranking']['variablenameresults']['totalvariablenames'] = 0
		jsonreport['ranking']['variablenameresults']['versionresults'] = []
		if 'totalnames' in variablenameresults:
			jsonreport['ranking']['variablenameresults']['totalvariablenames'] = variablenameresults['totalnames']
		if 'versionresults' in variablenameresults:
			for packagename in variablenameresults['versionresults']:
				packagereport = {}
				packagereport['packagename'] = packagename
				packagereport['unique'] = []
				for un in variablenameresults['versionresults'][packagename]:
					(identifier, identifierdata) = un
					uniquereport = {}
					uniquereport['identifier'] = identifier
					uniquereport['identifierdata'] = []
					for iddata in identifierdata:
						(filechecksum, linenumber, fileversiondata) = iddata
						identifierdatareport = {}
						if outputhash != None and outputhash != 'sha256':
							if filechecksum in hashcache:
								identifierdatareport['filechecksum'] = hashcache[filechecksum]
								identifierdatareport['filechecksumtype'] = outputhash
							else:
								cursor.execute(query, (filechecksum,))
								convertedhash = cursor.fetchone()
								if convertedhash != None:
									hashcache[filechecksum] = convertedhash[0]
									identifierdatareport['filechecksum'] = convertedhash[0]
									identifierdatareport['filechecksumtype'] = outputhash
								else:
									identifierdatareport['filechecksum'] = filechecksum
									identifierdatareport['filechecksumtype'] = 'sha256'
						else:
							identifierdatareport['filechecksum'] = filechecksum
							identifierdatareport['filechecksumtype'] = 'sha256'
						identifierdatareport['linenumber'] = linenumber
						identifierdatareport['packagedata'] = []
						for pack in fileversiondata:
							(packageversion, sourcefilename) = pack
							fileversionreport = {}
							fileversionreport['packageversion'] = packageversion
							fileversionreport['sourcefilename'] = sourcefilename
							identifierdatareport['packagedata'].append(fileversionreport)
						uniquereport['identifierdata'].append(identifierdatareport)
					packagereport['unique'].append(uniquereport)
				jsonreport['ranking']['variablenameresults']['versionresults'].append(packagereport)

	## then security information
	## TODO
	if batconnection != None:
		cursor.close()
		batconnection.close()

	## dump the JSON to a file
	jsonfile = gzip.open(os.path.join(topleveldir, "reports", "%s.json.gz" % filehash), 'w')
	jsonfile.write(json.dumps(jsonreport, indent=4))
	jsonfile.close()

def printjson(unpackreports, scantempdir, topleveldir, processors, scanenv={}, scandebug=False, unpacktempdir=None):
	toplevelelem = None
	for u in unpackreports:
		if "toplevel" in unpackreports[u]['tags']:
			toplevelelem = u
			break

	## first the data needs to be a bit mangled
	jsondumps = []

	if "OUTPUTHASH" in scanenv:
		outputhash = scanenv['OUTPUTHASH']
	else:
		outputhash = None

	if outputhash != None and outputhash != 'sha256':
		if not 'DBBACKEND' in scanenv:
			return
		batdb = bat.batdb.BatDb(scanenv['DBBACKEND'])
		if not scanenv.has_key('BAT_DB'):
			return
	else:
		batdb = None

	for unpackreport in unpackreports:
		jsonreport = {}
		filehash = None
		if "sha256" in unpackreports[unpackreport]:
			filehash = copy.deepcopy(unpackreports[unpackreport]['sha256'])
			jsonreport['checksum'] = filehash
			jsonreport['checksumtype'] = 'sha256'
		if "name" in unpackreports[unpackreport]:
			name = copy.deepcopy(unpackreports[unpackreport]['name'])
			## check whether or not the name of the file does not contain any weird
			## characters by decoding it to UTF-8
			decoded = False
			for i in ['utf-8', 'ascii', 'latin-1']:
				try:
					name = name.decode(i)
					decoded = True
					break
				except Exception, e:
					pass
			if decoded:
				jsonreport['name'] = name
			else:
				if filehash != None:
					jsonreport['name'] = "name-for-%s-cannot-be-displayed" % filehash
				else:
					continue
		if "path" in unpackreports[unpackreport]:
			jsonreport['path'] = copy.deepcopy(unpackreports[unpackreport]['path'])
		if "realpath" in unpackreports[unpackreport]:
			jsonreport['realpath'] = copy.deepcopy(unpackreports[unpackreport]['realpath'])
		if "tags" in unpackreports[unpackreport]:
			jsonreport['tags'] = list(set(copy.deepcopy(unpackreports[unpackreport]['tags'])))
		if "magic" in unpackreports[unpackreport]:
			jsonreport['magic'] = copy.deepcopy(unpackreports[unpackreport]['magic'])
		if "sha256" in unpackreports[unpackreport]:
			jsonreport['checksum'] = filehash
			jsonreport['checksumtype'] = 'sha256'
		if "scans" in unpackreports[unpackreport]:
			if unpackreports[unpackreport]['scans'] != []:
				jsonreport['scans'] = copy.deepcopy(unpackreports[unpackreport]['scans'])
		jsondumps.append(jsonreport)

	if jsondumps != []:
		jsonfile = open(os.path.join(topleveldir, "scandata.json"), 'w')
		jsonfile.write(json.dumps(jsondumps, indent=4))
		jsonfile.close()

	filehashes = set()
	jsontasks = []

	## create tasks for printing results for each of the individual reports
	for unpackreport in unpackreports:
		## first see if there is a filehash. If not, continue
		if not "sha256" in unpackreports[unpackreport]:
			continue
		filehash = unpackreports[unpackreport]['sha256']
		if filehash in filehashes:
			continue
		## then check if there is a pickle file. If not, continue
		if not os.path.exists(os.path.join(topleveldir, "filereports", "%s-filereport.pickle" % filehash)):
			continue
		## then check if the data for this file has already been dumped (this should not
		## happen). If so, continue.
		if os.path.exists(os.path.join(topleveldir, "reports", "%s.json.gz" % filehash)):
			continue
		filehashes.add(filehash)
		jsontasks.append((filehash, topleveldir, outputhash, scanenv['BAT_DB'], batdb, scanenv))

	pool = multiprocessing.Pool(processes=processors)
	pool.map(writejson, jsontasks,1)
	pool.terminate()
