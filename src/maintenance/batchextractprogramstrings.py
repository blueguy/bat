#!/usr/bin/python
# -*- coding: utf-8 -*-

## Binary Analysis Tool
## Copyright 2009-2012 Armijn Hemel for Tjaldur Software Governance Solutions
## Licensed under Apache 2.0, see LICENSE file for details

'''
Program to process a whole directory full of compressed source code archives
to create a knowledgebase. Needs a file LIST in the directory it is passed as
a parameter, which has the following format:

package version filename origin

separated by whitespace

Compression is determined using magic
'''

import sys, os, magic, string, re, subprocess, shutil, stat
import tempfile, bz2, tarfile, gzip
from optparse import OptionParser
from multiprocessing import Pool
import sqlite3, hashlib

tarmagic = ['POSIX tar archive (GNU)'
           , 'tar archive'
           ]

ms = magic.open(magic.MAGIC_NONE)
ms.load()

## list of extensions, plus what language they should be mapped to
## This is not necessarily correct, but right now it is the best we have.
extensions = {'.c'      : 'C',
              '.cc'     : 'C',
              '.cpp'    : 'C',
              '.cxx'    : 'C',
              '.c++'    : 'C',
              '.h'      : 'C',
              '.hh'     : 'C',
              '.hpp'    : 'C',
              '.hxx'    : 'C',
              '.qml'    : 'C',
              '.s'      : 'C',
              '.txx'    : 'C',
              '.cs'     : 'C#',
              '.groovy' : 'Java',
              '.java'   : 'Java',
              '.jsp'    : 'Java',
              '.scala'  : 'Java',
              '.as'     : 'ActionScript',
              '.js'     : 'JavaScript',
             }

## a list of characters that 'strings' will split on when processing a binary file
splitcharacters = map(lambda x: chr(x), range(0,9) + range(14,32) + [127])

## split on the special characters, plus remove special control characters that are
## at the beginning and end of the string in escaped form.
## Return a list of strings.
def splitSpecialChars(s):
	splits = [s]
	final_splits = []
	splitchars = []
	for i in splitcharacters:
		if i in s:
			splitchars.append(i)
	if splitchars != []:
		for i in splitchars:
			splits = filter(lambda x: x != '', reduce(lambda x, y: x + y, map(lambda x: x.split(i), splits), []))
	## Now we need to make sure we get rid of leading control characters.
	## The reason we remove them only at the beginning and end
	## (for now) is because it is a lot easier. In the future we should also
	## split on them mid-string.
	remove_chars = ["\\a", "\\b", "\\v", "\\f", "\\n", "\\r", "\\e", "\\0"]
	for i in splits:
		processed = False
		lensplit = len(i)
		while not processed and lensplit != 0:
			for c in remove_chars:
				if i.startswith(c):
					i = i[2:]
					break
				if i.endswith(c) and len(i) > 3:
					if i[-3] != "\\":
						i = i[:-2]
						break
			if lensplit == len(i):
				processed = True
				final_splits.append(i)
				break
			else:
				lensplit = len(i)
	return final_splits

## unpack the directories to be scanned. For speed improvements it might be
## wise to use a ramdisk or tmpfs for this, although when using Ninka and
## FOSSology it is definitely not I/O bound...
def unpack(directory, filename):
	try:
		os.stat("%s/%s" % (directory, filename))
	except:
		print >>sys.stderr, "Can't find %s" % filename
		return None

        filemagic = ms.file(os.path.realpath("%s/%s" % (directory, filename)))

        ## Assume if we have bz2 or gzip compressed file we are dealing with compressed tar files
        if 'bzip2 compressed data' in filemagic:
       		tmpdir = tempfile.mkdtemp()
		## for some reason the tar.bz2 unpacking from python doesn't always work, like
		## aeneas-1.0.tar.bz2 from GNU, so use a subprocess instead of using the
		## Python tar functionality.
 		p = subprocess.Popen(['tar', 'jxf', "%s/%s" % (directory, filename)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=True, cwd=tmpdir)
		(stanout, stanerr) = p.communicate()
		return tmpdir
        elif 'XZ compressed data' in filemagic:
       		tmpdir = tempfile.mkdtemp()
 		p = subprocess.Popen(['tar', 'Jxf', "%s/%s" % (directory, filename)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=True, cwd=tmpdir)
		(stanout, stanerr) = p.communicate()
		return tmpdir
        elif 'gzip compressed data' in filemagic:
       		tmpdir = tempfile.mkdtemp()
 		p = subprocess.Popen(['tar', 'zxf', "%s/%s" % (directory, filename)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=True, cwd=tmpdir)
		(stanout, stanerr) = p.communicate()
		return tmpdir
	elif 'Zip archive data' in filemagic:
		try:
       			tmpdir = tempfile.mkdtemp()
			p = subprocess.Popen(['unzip', "-B", "%s/%s" % (directory, filename), '-d', tmpdir], stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=True)
			(stanout, stanerr) = p.communicate()
			if p.returncode != 0 and p.returncode != 1:
				print >>sys.stderr, "unpacking ZIP failed for", filename, stanerr
				shutil.rmtree(tmpdir)
				pass
			else:
				return tmpdir
		except Exception, e:
			print >>sys.stderr, "unpacking ZIP failed", e

def unpack_verify(filedir, filename):
	try:
		os.stat("%s/%s" % (filedir, filename))
	except:
		print >>sys.stderr, "Can't find %s" % filename

## get strings plus the license. This method should be renamed to better
## reflect its true functionality...
def unpack_getstrings(filedir, package, version, filename, origin, filehash, dbpath, cleanup, license, copyrights, pool, ninkacomments, licensedb, oldpackage, oldsha256):
	print >>sys.stdout, filename

	## Check if we've already processed this file. If so, we can easily skip it and return.
	## TODO: we should take the origin into account, because sometimes there are differences
	## in packages with the same name from different sources (binutils-2.1[567] from GNU for
	## example got a license change in mid-2011, without package names being updated)
        conn = sqlite3.connect(dbpath, check_same_thread = False)
	c = conn.cursor()
	c.execute('PRAGMA synchronous=off')
	## unpack the archive. If we fail, cleanup and return.
	temporarydir = unpack(filedir, filename)
	if temporarydir == None:
		c.close()
		conn.close()
		return None
	## Check if we already have any strings from program + version. If so,
	## first remove them before we add them to avoid unnecessary duplication.
	c.execute('''select sha256 from processed_file where package=? and version=? LIMIT 1''', (package, version))
	if len(c.fetchall()) != 0:
		c.execute('''delete from processed_file where package=? and version=?''', (package, version))
		conn.commit()

	sqlres = traversefiletree(temporarydir, conn, c, package, version, license, copyrights, pool, ninkacomments, licensedb, oldpackage, oldsha256)
	## Add the file to the database: name of archive, sha256, packagename and version
	## This is to be able to just update the database instead of recreating it.
	c.execute('''insert into processed (package, version, filename, origin, sha256) values (?,?,?,?,?)''', (package, version, filename, origin, filehash))
	conn.commit()
	c.close()
	conn.close()
	if cleanup:
		try:
			osgen = os.walk(temporarydir)
			while True:
				i = osgen.next()
				## make sure we can access all directories
				for d in i[1]:
					if not os.path.islink("%s/%s" % (i[0], d)):
						os.chmod("%s/%s" % (i[0], d), stat.S_IRUSR|stat.S_IWUSR|stat.S_IXUSR)
				for p in i[2]:
					try:
						if not os.path.islink("%s/%s" % (i[0], p)):
							os.chmod("%s/%s" % (i[0], p), stat.S_IRUSR|stat.S_IWUSR|stat.S_IXUSR)
					except Exception, e:
						#print e
						pass
		except StopIteration:
			pass
		try:
			shutil.rmtree(temporarydir)
		except:
			## nothing we can do right now, so just give up
			pass
	return sqlres

def computehash((path, filename)):
	try:
		if not os.path.islink("%s/%s" % (path, filename)):
			os.chmod("%s/%s" % (path, filename), stat.S_IRUSR|stat.S_IWUSR|stat.S_IXUSR)
	except Exception, e:
		pass
	## skip links
	if os.path.islink("%s/%s" % (path, filename)):
        	return None
	## we can't determine anything about an empty file, so skip
	if os.stat("%s/%s" % (path, filename)).st_size == 0:
		return None
	## some filenames might have uppercase extensions, so lowercase them first
	p_nocase = filename.lower()
	process = False
	for extension in extensions.keys():
		if (p_nocase.endswith(extension)):
			process = True
			break

	if not process:
		return None
	filemagic = ms.file(os.path.realpath("%s/%s" % (path, filename)))
	if filemagic == "AppleDouble encoded Macintosh file":
		return None
	scanfile = open("%s/%s" % (path, filename), 'r')
	h = hashlib.new('sha256')
	h.update(scanfile.read())
	scanfile.close()
	filehash = h.hexdigest()
	return (path, filename, filehash, extension)

def traversefiletree(srcdir, conn, cursor, package, version, license, copyrights, pool, ninkacomments, licensedb, oldpackage, oldsha256):
	srcdirlen = len(srcdir)+1
	osgen = os.walk(srcdir)
	ninkaversion = "bf83428"

	try:
		filestoscan = []
		filehashes = {}
		tmpsha256s = []
		scanfiles = []
		while True:
			i = osgen.next()
			## make sure we can access all directories
			for d in i[1]:
				if not os.path.islink("%s/%s" % (i[0], d)):
					os.chmod("%s/%s" % (i[0], d), stat.S_IRUSR|stat.S_IWUSR|stat.S_IXUSR)
			for p in i[2]:
				scanfiles.append((i[0], p))
	except Exception, e:
		if str(e) != "":
			print >>sys.stderr, package, version, e
			return
		pass

	## compute the hashes in parallel
	scanfile_result = filter(lambda x: x != None, pool.map(computehash, scanfiles, 1))

	insertfiles = []

	## loop through the files to see which files should be scanned.
	## A few assumptions are made:
	## * all tables are in a consistent state
	## * all tables are generated at the same time
	## So this is not robust if one of the databases (say, licenses)
	## is modified by another tool, or deleted and needs to be
	## regenerated.
	for s in scanfile_result:
		(path, filename, filehash, extension) = s
		insertfiles.append(("%s/%s" % (path[srcdirlen:],filename), filehash))

		## if we process many versions of a single package there is likely going to be
		## overlap. We can avoid hitting the disk by remembering the SHA256 from a previous
		## run.
		if package == oldpackage:
			if s[2] in oldsha256:
				continue
		if filehash in tmpsha256s:
			continue
		cursor.execute("select * from processed_file where sha256=? LIMIT 1", (filehash,))
		testres = cursor.fetchall()
		if len(testres) != 0:
			continue
		tmpsha256s.append(filehash)
		cursor.execute('''select * from extracted_file where sha256=? LIMIT 1''', (filehash,))
		if len(cursor.fetchall()) != 0:
			#print >>sys.stderr, "duplicate %s %s: %s/%s" % (package, version, i[0], p)
			continue
		filestoscan.append((package, version, path, filename, extensions[extension], filehash, ninkaversion))
		if filehashes.has_key(filehash):
			filehashes[filehash].append((path, filename))
		else:
			filehashes[filehash] = [(path, filename)]

	## first check licenses, since we do sometimes manipulate some source code files
	if license:
		ninkaconn = sqlite3.connect(ninkacomments, check_same_thread = False)
		ninkacursor = ninkaconn.cursor()

		licenseconn = sqlite3.connect(licensedb, check_same_thread = False)
		licensecursor = licenseconn.cursor()
		licensecursor.execute('PRAGMA synchronous=off')

		## this is just an extra sanity check. This should not be triggered, but
		## in case some data has been deleted it might come in handy.
		#commentsfiletoscan = []
		#for i in filestoscan:
		#	lres = licensecursor.execute('''select sha256 from licenses where sha256 = ? and scanner = ? and version = ? LIMIT 1''', (i[5], "ninka", ninkaversion)).fetchall()
		#	if lres != []:
		#		continue
		#	else:
		#		commentsfiletoscan.append(i)

		#comments_results = pool.map(extractcomments, commentsfiletoscan, 1)

		comments_results = pool.map(extractcomments, filestoscan, 1)
		commentshash = {}
		commentshash2 = {}
		for c in comments_results:
			if commentshash.has_key(c[0]):
				continue
			else:
				commentshash[c[0]] = c[1]
			if commentshash2.has_key(c[1]):
				commentshash2[c[1]].append(c[0])
			else:
				commentshash2[c[1]] = [c[0]]

		licensefilestoscan = []
		for c in commentshash2:
			ninkacursor.execute('''select license, version from ninkacomments where sha256=?''', (c,))
			res = ninkacursor.fetchall()
			if len(res) > 0:
				## store all the licenses we already know for this comment
				for r in res:
					(filelicense, scannerversion) = r
					for f in commentshash2[c]:
						## only use this if we actually have duplications
						#licensecursor.execute('''delete from licenses where sha256 = ? and license = ? and scanner = ? and version = ?''', (f, filelicense, "ninka", scannerversion))
						licensecursor.execute('''insert into licenses (sha256, license, scanner, version) values (?,?,?,?)''', (f, filelicense, "ninka", scannerversion))
			else:
				licensefilestoscan.append(commentshash2[c][0])
		licenseconn.commit()

		licensescanfiles = []

		for l in licensefilestoscan:
			licensescanfiles.append((filehashes[l][0][0], filehashes[l][0][1], l, ninkaversion))
		license_results = pool.map(runfullninka, licensescanfiles, 1)

		## we now know the licenses for files we didn't know before. So:
		## 1. find the corresponding commentshash
		## 2. store the licenses for this file, plus for the commentshash
		## 3. for each file that has the same commentshash, store the license as well
		for l in license_results:
			licenses = l[1]
			for license in licenses:
				ninkacursor.execute('''insert into ninkacomments (sha256, license, version) values (?,?,?)''', (commentshash[l[0]], license, ninkaversion))
				for f in commentshash2[commentshash[l[0]]]:
					licensecursor.execute('''insert into licenses (sha256, license, scanner, version) values (?,?,?,?)''', (f, license, "ninka", ninkaversion))
		licenseconn.commit()
		ninkaconn.commit()

		## cleanup
		ninkacursor.close()
		ninkaconn.close()

		## TODO: sync names of licenses as found by FOSSology and Ninka
		## TODO: dynamically determine the version of FOSSology
		fossology_chunksize = 10
		fossology_filestoscan = []
		for i in range(0,len(filestoscan),fossology_chunksize):
			fossology_filestoscan.append((filestoscan[i:i+fossology_chunksize]))
		fossology_res = filter(lambda x: x != None, pool.map(licensefossology, fossology_filestoscan, 1))
		fossology_version = "2.1.0"
		for f in fossology_res:
			for ff in f:
				(filehash, fres) = ff
				for license in fres:
					#licensecursor.execute('''delete from licenses where sha256 = ? and license = ? and scanner = ? and version = ?''', (filehash, license, "fossology", fossology_version))
					licensecursor.execute('''insert into licenses (sha256, license, scanner, version) values (?,?,?,?)''', (filehash, license, "fossology", fossology_version))
		licenseconn.commit()
		licensecursor.close()
		licenseconn.close()


	## extract copyrights
	if copyrights:
		licenseconn = sqlite3.connect(licensedb, check_same_thread = False)
		licensecursor = licenseconn.cursor()
		licensecursor.execute('PRAGMA synchronous=off')

		copyrightsres = pool.map(extractcopyrights, filestoscan, 1)
		if copyrightsres != None:
			for c in filter(lambda x: x != None, copyrightsres):
				(filehash, cres) = c
				for cr in cres:
					## OK, this delete is *really* stupid because we don't have an index for this
					## combination of parameters.
					#licensecursor.execute('''delete from extracted_copyright where sha256 = ? and copyright = ? and type = ? and offset = ?''', (filehash, cr[1], cr[0], cr[2]))
					licensecursor.execute('''insert into extracted_copyright (sha256, copyright, type, offset) values (?,?,?,?)''', (filehash, cr[1], cr[0], cr[2]))
		licenseconn.commit()
		licensecursor.close()
		licenseconn.close()

	## process the files we want to scan in parallel, then process the results
	extracted_results = pool.map(extractstrings, filestoscan, 1)

	for extractres in extracted_results:
		(filehash, language, sqlres, cresults, javaresults) = extractres
		for res in sqlres:
			(pstring, linenumber) = res
			cursor.execute('''insert into extracted_file (programstring, sha256, language, linenumber) values (?,?,?,?)''', (pstring, filehash, language, linenumber))
		for res in list(set(cresults)):
			(cname, linenumber, nametype) = res
			if nametype == 'function':
				cursor.execute('''insert into extracted_function (sha256, functionname, language, linenumber) values (?,?,?,?)''', (filehash, cname, 'C', linenumber))
			else:
				cursor.execute('''insert into extracted_name (sha256, name, type, language, linenumber) values (?,?,?,?,?)''', (filehash, cname, nametype, 'C', linenumber))
		for res in list(set(javaresults)):
			(cname, linenumber, nametype) = res
			if nametype == 'method':
				cursor.execute('''insert into extracted_function (sha256, functionname, language, linenumber) values (?,?,?,?)''', (filehash, cname, 'Java', linenumber))
			else:
				cursor.execute('''insert into extracted_name (sha256, name, type, language, linenumber) values (?,?,?,?,?)''', (filehash, cname, nametype, 'Java', linenumber))
	conn.commit()

	for i in insertfiles:
		cursor.execute('''insert into processed_file (package, version, filename, sha256) values (?,?,?,?)''', (package, version, i[0], i[1]))
	conn.commit()
	return (scanfile_result)

## extract comments in parallel
def extractcomments((package, version, i, p, language, filehash, ninkaversion)):
	## first we generate just a .comments file and see if we've already seen it
	## before. This is because often license headers are very similar, so we
	## don't need to rescan everything.
	## For gtk+ 2.20.1 scanning time dropped with about 25%.
	ninkaenv = os.environ.copy()
	ninkabasepath = '/tmp/dmgerman-ninka-%s' % ninkaversion
	ninkaenv['PATH'] = ninkaenv['PATH'] + ":%s/comments/comments" % ninkabasepath

	p1 = subprocess.Popen(["%s/ninka.pl" % ninkabasepath, "-c", "%s/%s" % (i, p)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=ninkaenv)
	(stanout, stanerr) = p1.communicate()
	scanfile = open("%s/%s.comments" % (i, p), 'r')
	ch = hashlib.new('sha256')
	ch.update(scanfile.read())
	scanfile.close()
	commentshash = ch.hexdigest()
	return (filehash, commentshash)

def runfullninka((i, p, filehash, ninkaversion)):
	ninkaenv = os.environ.copy()
	ninkabasepath = '/tmp/dmgerman-ninka-%s' % ninkaversion
	ninkaenv['PATH'] = ninkaenv['PATH'] + ":%s/comments/comments" % ninkabasepath

	ninkares = []

	p2 = subprocess.Popen(["%s/ninka.pl" % ninkabasepath, "%s/%s" % (i, p)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=ninkaenv)
	(stanout, stanerr) = p2.communicate()
	ninkasplit = stanout.strip().split(';')[1:]
	## filter out the licenses we can't determine.
	if ninkasplit[0] == '':
		ninkares = ['UNKNOWN']
	else:
		licenses = ninkasplit[0].split(',')
		ninkares = list(set(licenses))
	return (filehash, ninkares)

def extractcopyrights((package, version, i, p, language, filehash, ninkaversion)):
	copyrightsres = []
	p2 = subprocess.Popen(["/usr/share/fossology/copyright/agent/copyright", "-C", "%s/%s" % (i, p)], stdin=subprocess.PIPE, stderr=subprocess.PIPE, stdout=subprocess.PIPE)
	(stanout, stanerr) = p2.communicate()
	if "FATAL" in stanout:
		## TODO: better error handling
		return None
	else:
		clines = stanout.split("\n")
		continuation = True
		bufstr = ""
		buftype = ""
		offset = 0
		for c in clines[1:]:
			## Extract copyright information, like URLs, e-mail
			## addresses and copyright statements.
			## Copyright statements and URLs are not very accurate.
			## URLs extracted from BusyBox for example contain links
			## to standards, RFCs, other project's bug trackers, and
			## so on. It is not a good indicator of anything
			## unless some extra filtering is added, like searching for
			## URLs that point to licenses that were not included in
			## the binary.
			res = re.match('^\[(\d+):\d+:(\w+)] \'(.*)\'', c.strip())
			if res != None:
				if continuation:
					if bufstr != "" and buftype != "":
						copyrightsres.append((buftype, bufstr, offset))
				continuation = False
				bufstr = ""
				buftype = ""
				offset = res.groups()[0]
				## e-mail addresses are never on multiple lines
				if res.groups()[1] == 'email':
					copyrightsres.append(('email', res.groups()[2], offset))
					offset
				## urls should are never on multiple lines
				elif res.groups()[1] == 'url':
					copyrightsres.append(('url', res.groups()[2], offset))
				## copyright statements can be on multiple lines, but this is
				## the start of a new statement
				elif res.groups()[1] == 'statement':
					continuation = True
					buftype = "statement"
					bufstr = res.groups()[2]
			else:
				res = re.match('^\[(\d+):\d+:(\w+)] \'(.*)', c.strip())
				if res != None:
					if res.groups()[1] == 'statement':
						continuation = True
						buftype = "statement"
						bufstr = res.groups()[2]
						offset = res.groups()[0]
				else:
					bufstr = bufstr + "\n" + c.strip()
					continuation = True
		## perhaps some lingering data
		if continuation:
			if bufstr != "" and buftype != "":
				copyrightsres.append((buftype, bufstr, offset))
		## TODO: clean up 'statement' and 'url', since there is quite a
		## bit of bogus data present.
	return (filehash, copyrightsres)

def licensefossology((packages)):
	## Also run FOSSology. This requires that the user has enough privileges to actually connect to the
	## FOSSology database, for example by being in the correct group.
	fossologyres = []
	fossscanfiles = map(lambda x: "%s/%s" % (x[2], x[3]), packages)
	scanargs = ["/usr/share/fossology/nomos/agent/nomos"] + fossscanfiles
	p2 = subprocess.Popen(scanargs, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
	(stanout, stanerr) = p2.communicate()
	if "FATAL" in stanout:
		## TODO: better error handling
		return None
	else:
		fosslines = stanout.strip().split("\n")
		for j in range(0,len(fosslines)):
			fossysplit = fosslines[j].strip().rsplit(" ", 1)
			licenses = fossysplit[-1].split(',')
			fossologyres.append((packages[j][5], list(set(licenses))))
	return fossologyres
	p2 = subprocess.Popen(["/usr/share/fossology/nomos/agent/nomos", "%s/%s" % (i, p)], stdin=subprocess.PIPE, stderr=subprocess.PIPE, stdout=subprocess.PIPE)
	(stanout, stanerr) = p2.communicate()
	if "FATAL" in stanout:
		## TODO: better error handling
		return None
	else:
		fossysplit = stanout.strip().rsplit(" ", 1)
		licenses = fossysplit[-1].split(',')
		fossologyres = list(set(licenses))
	return (filehash, fossologyres)

## TODO: get rid of ninkaversion before we call this method
## TODO: process more files at once to reduce overhead of calling ctags
def extractstrings((package, version, i, p, language, filehash, ninkaversion)):
	sqlres = extractsourcestrings(p, i, language)
	## extract function names using ctags, except code from
	## the Linux kernel, since it will never be dynamically linked
	# (name, linenumber, type)
	cresults = []

	## this is specifically for Java
	# (name, type, linenumber)
	javaresults = []
	if (language == 'C' or language == 'Java') and package != 'linux':
		source = open(os.path.join(i, p)).read()

		p2 = subprocess.Popen(["ctags", "-f", "-", "-x", "%s/%s" % (i, p)], stdin=subprocess.PIPE, stderr=subprocess.PIPE, stdout=subprocess.PIPE)
		(stanout2, stanerr2) = p2.communicate()
		if p2.returncode != 0:
			funcresults = []
		elif stanout2.strip() == "":
			funcresults = []
		else:
			stansplit = stanout2.strip().split("\n")
			for res in stansplit:
				csplit = res.strip().split()
				if filter(lambda x: x not in string.printable, csplit[0]) != "":
					continue
				if language == 'C':
					for i in ['function', 'variable']:
						if csplit[1] == i:
							cresults.append((csplit[0], int(csplit[2]), i))
				if language == 'Java':
					for i in ['method', 'class', 'field']:
						if csplit[1] == i:
							javaresults.append((csplit[0], int(csplit[2]), i))

	return (filehash, language, sqlres, cresults, javaresults)

## Extract strings using xgettext. Apparently this does not always work correctly. For example for busybox 1.6.1:
## $ xgettext -a -o - fdisk.c
##  xgettext: Non-ASCII string at fdisk.c:203.
##  Please specify the source encoding through --from-code.
## We fix this by rerunning xgettext with --from-code=utf-8
## The results might not be perfect, but they are acceptable.
## TODO: use version from bat/extractor.py
## TODO: process more files at once to reduce overhead of calling xgettext
def extractsourcestrings(filename, filedir, language):
	remove_chars = ["\\a", "\\b", "\\v", "\\f", "\\e", "\\0"]
	sqlres = []
	## for files that we think are in the 'C' family we first check for unprintable
	## characters like \0. xgettext doesn't like these and will stop as soon as it
	## encounters one of these characters, possibly missing out on some very significant
	## strings that we *do* want to see because they end up in the binary. We replace
	## them with \n, then run xgettext.
	## TODO: fix for octal values, like \010
	if language == 'C':
		changed = False
		scanfile = open("%s/%s" % (filedir, filename))
		filecontents = scanfile.read()
		scanfile.close()
		for r in remove_chars:
			if r in filecontents:
				changed = True
				filecontents = filecontents.replace(r, '\\n')
		if changed:
			scanfile = open("%s/%s" % (filedir, filename), 'w')
			scanfile.write(filecontents)
			scanfile.close()
	p1 = subprocess.Popen(['xgettext', '-a', "--omit-header", "--no-wrap", "%s/%s" % (filedir, filename), '-o', '-'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=True)
	(stanout, stanerr) = p1.communicate()
	if p1.returncode != 0:
		## analyze stderr first
		if "Non-ASCII" in stanerr:
			## rerun xgettext with a different encoding
			p2 = subprocess.Popen(['xgettext', '-a', "--omit-header", "--no-wrap", "--from-code=utf-8", "%s/%s" % (filedir, filename), '-o', '-'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=True)
			## overwrite stanout
			(stanout, pstanerr) = p2.communicate()
			if p2.returncode != 0:
				return sqlres
	source = stanout 
	lines = []
	linenumbers = []

	## escape just once to speed up extraction of filenumbers
	filename_escape = re.escape(filename)

	for l in stanout.split("\n"):
		## skip comments and hints
		if l.startswith("#, "):
			continue
		if l.startswith("#: "):
			## there can actually be more than one entry on a single line
			res = re.findall("%s:(\d+)" % (filename_escape,), l[3:])
			if res != None:
				linenumbers = linenumbers + map(lambda x: int(x), res)
			else:
				linenumbers.append(0)

		if l.startswith("msgid "):
			lines = []
			lines.append(l[7:-1])
		## when we see msgstr "" we have reached the end of a block and we can start
		## processing
		elif l.startswith("msgstr \"\""):
			count = len(linenumbers)
			for xline in lines:
				splits=splitSpecialChars(xline)
				if splits == []:
					continue
				for splitline in splits:
					for line in splitline.split("\\r\\n"):
						for sline in line.split("\\n"):
							## do we really need this?
							sline = sline.replace("\\\n", "")

							## unescape a few values
							sline = sline.replace("\\\"", "\"")
							sline = sline.replace("\\t", "\t")
							sline = sline.replace("\\\\", "\\")
	
							## we don't want to store empty strings, they won't show up in binaries
							## but they do make the database a lot larger
							if sline == '':
								continue
							for i in range(0, len(linenumbers)):
								sqlres.append((sline, linenumbers[i]))
			linenumbers = []
		## the other strings are added to the list of strings we need to process
		else:
			lines.append(l[1:-1])
	return sqlres

def checkalreadyscanned((filedir, package, version, filename, origin, dbpath)):
	try:
		os.stat("%s/%s" % (filedir, filename))
	except:
		print >>sys.stderr, "Can't find %s" % filename
		return None
	scanfile = open("%s/%s" % (filedir, filename), 'r')
	h = hashlib.new('sha256')
	h.update(scanfile.read())
	scanfile.close()
	filehash = h.hexdigest()

	## Check if we've already processed this file. If so, we can easily skip it and return.
	## TODO: we should take the origin into account, because sometimes there are differences
	## in packages with the same name from different sources (binutils-2.1[567] from GNU for
	## example got a license change in mid-2011, without package names being updated)

	## TODO: we actually should check if we know the *checksum* first, because a package could
	## have been renamed.
        conn = sqlite3.connect(dbpath, check_same_thread = False)
	c = conn.cursor()
	#c.execute('PRAGMA synchronous=off')
	#c.execute('''select * from processed where package=? and version=? and origin=?''', (package, version, origin))
	c.execute('''select * from processed where package=? and version=? LIMIT 1''', (package, version))
	if len(c.fetchall()) != 0:
		res = None
	else:
		res = (package, version, filename, origin, filehash)
	c.close()
	conn.close()
	return res

def main(argv):
	parser = OptionParser()
	parser.add_option("-b", "--blacklist", action="store", dest="blacklist", help="path to blacklist file", metavar="FILE")
	parser.add_option("-c", "--copyrights", action="store_true", dest="copyrights", help="extract copyrights (default: false)")
	parser.add_option("-d", "--database", action="store", dest="db", help="path to database", metavar="FILE")
	parser.add_option("-f", "--filedir", action="store", dest="filedir", help="path to directory containing files to unpack", metavar="DIR")
	parser.add_option("-l", "--licenses", action="store_true", dest="licenses", help="extract licenses (default: false)")
	parser.add_option("-n", "--ninkacomments", action="store", dest="ninkacomments", help="path to ninkacomments database", metavar="FILE")
	parser.add_option("-r", "--licensedb", action="store", dest="licensedb", help="path to licenses/copyrights database", metavar="FILE")
	parser.add_option("-v", "--verify", action="store_true", dest="verify", help="verify files, don't process (default: false)")
	parser.add_option("-w", "--wipe", action="store_true", dest="wipe", help="wipe database instead of update (default: false)")
	parser.add_option("-z", "--cleanup", action="store_true", dest="cleanup", help="cleanup after unpacking? (default: false)")
	(options, args) = parser.parse_args()
	if options.filedir == None:
		parser.error("Specify dir with files")
	else:
		try:
			filelist = open(options.filedir + "/LIST").readlines()
		except:
			parser.error("'LIST' not found in file dir")

	if options.db == None:
		parser.error("Specify path to database")

	if options.blacklist != None:
		try:
			blacklistlines = open(options.blacklist).readlines()
		except:
			parser.error("blacklist defined but not found/accessible")
	else:
		blacklistlines = []

	## TODO: fix format for blacklist
	## package version filename origin sha256sum
	## with sha256sum being decisive 
	blacklistsha256sums = []
	for i in blacklistlines:
		try:
			unpacks = i.strip().split()
			(package, version, filename, origin, sha256sum) = unpacks
			blacklistsha256sums.append(sha256sum)
		except Exception, e:
			# oops, something went wrong
			print >>sys.stderr, e

	if options.cleanup != None:
		cleanup = True
	else:
		cleanup = False

	if options.wipe != None:
		wipe = True
	else:
		wipe = False

	if options.licenses != None:
		license = True
		## check if FOSSology is actually running
		p2 = subprocess.Popen(["/usr/share/fossology/nomos/agent/nomos", "-h"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
		(stanout, stanerr) = p2.communicate()
		if "FATAL" in stanerr:
			print >>sys.stderr, "ERROR: license scanning enabled, but FOSSology not running"
			sys.exit(1)
		if options.ninkacomments == None:
			parser.error("License scanning enabled, but no path to ninkacomments database supplied")
		if options.ninkacomments == options.db:
			parser.error("Database and ninkacomments database cannot be the same")
	else:
		license = False

	if options.copyrights != None:
		copyrights = True
		p2 = subprocess.Popen(["/usr/share/fossology/copyright/agent/copyright", "-h"], stdin=subprocess.PIPE, stderr=subprocess.PIPE, stdout=subprocess.PIPE)
		(stanout, stanerr) = p2.communicate()
		if "FATAL" in stanout:
			print >>sys.stderr, "ERROR: copyright extraction enabled, but FOSSology not running"
			sys.exit(1)
	else:
		copyrights = False

	if options.licenses != None and options.copyrights != None and options.licensedb == None:
		parser.error("Specify path to licenses/copyrights database")

	conn = sqlite3.connect(options.db, check_same_thread = False)
	c = conn.cursor()
	#c.execute('PRAGMA synchronous=off')

	if options.licenses:
		ninkaconn = sqlite3.connect(options.ninkacomments, check_same_thread = False)
		ninkac = ninkaconn.cursor()

	if options.licenses or options.copyrights:
		licenseconn = sqlite3.connect(options.licensedb, check_same_thread = False)
		licensec = licenseconn.cursor()
		#licensec.execute('PRAGMA synchronous=off')

	if wipe:
		try:
			c.execute('''drop table extracted''')
		except:
			pass
		try:
			c.execute('''drop table processed''')
		except:
			pass
		try:
			c.execute('''drop table processed_file''')
		except:
			pass
		try:
			c.execute('''drop table extracted_file''')
		except:
			pass
		try:
			licensec.execute('''drop table licenses''')
			licensec.execute('''drop table extracted_copyright''')
			licenseconn.commit()
		except:
			pass
		try:
			ninkac.execute('''drop table ninkacomments''')
			ninkaconn.commit()
		except:
			pass

		conn.commit()
        try:
		## Keep an archive of which packages and archive files (tar.gz, tar.bz2, etc.) we've already
		## processed, so we don't repeat work.
		c.execute('''create table if not exists processed (package text, version text, filename text, origin text, sha256 text)''')
		c.execute('''create index if not exists processed_index on processed(package, version)''')
		c.execute('''create index if not exists processed_checksum on processed(sha256)''')

		## Keep an archive of which packages are blacklisted. This is useful during database creation,
		## or during database expansion.
		#c.execute('''create table if not exists blacklist (package text, version text, filename text, origin text, sha256 text)''')
		#c.execute('''create index if not exists blacklist_index on blacklist(package, version)''')

		## Since there is a lot of duplication inside source packages we store strings per checksum
		## which we can later link with files
		c.execute('''create table if not exists processed_file (package text, version text, filename text, sha256 text)''')
		c.execute('''create index if not exists processedfile_index on processed_file(sha256)''')
		c.execute('''create index if not exists processedfile_package_index on processed_file(package)''')
		c.execute('''create unique index if not exists processedfile_package_index_unique on processed_file(package, version, filename, sha256)''')

		## Store the extracted strings per checksum, not per (package, version, filename).
		## This saves a lot of space in the database
		## The field 'language' denotes what 'language' (family) the file the string is extracted from
		## is in. Possible values: extensions.values()
		c.execute('''create table if not exists extracted_file (programstring text, sha256 text, language text, linenumber int)''')
		c.execute('''create index if not exists programstring_index on extracted_file(programstring)''')
		c.execute('''create index if not exists extracted_hash on extracted_file(sha256)''')
		c.execute('''create index if not exists extracted_language on extracted_file(language);''')

		## Store the function names extracted, per checksum
		c.execute('''create table if not exists extracted_function (sha256 text, functionname text, language text, linenumber int)''')
		c.execute('''create index if not exists function_index on extracted_function(sha256);''')
		c.execute('''create index if not exists functionname_index on extracted_function(functionname)''')
		c.execute('''create index if not exists functionname_language on extracted_function(language);''')

		## Store different information extracted with ctags
		c.execute('''create table if not exists extracted_name (sha256 text, name text, type text, language text, linenumber int)''')
		c.execute('''create index if not exists name_checksum_index on extracted_name(sha256);''')
		c.execute('''create index if not exists name_name_index on extracted_name(name)''')
		c.execute('''create index if not exists name_name_index on extracted_name(type)''')
		c.execute('''create index if not exists name_language_index on extracted_name(language);''')
		conn.commit()

		if options.licenses or options.copyrights:
			## Store the extracted licenses per checksum.
			licensec.execute('''create table if not exists licenses (sha256 text, license text, scanner text, version text)''')
			licensec.execute('''create index if not exists license_index on licenses(sha256);''')

			## Store the copyrights extracted by FOSSology, per checksum
			## type can be:
			## * email
			## * statement
			## * url
			licensec.execute('''create table if not exists extracted_copyright (sha256 text, copyright text, type text, offset int)''')
			licensec.execute('''create index if not exists copyright_index on extracted_copyright(sha256);''')
			licensec.execute('''create index if not exists copyright_type_index on extracted_copyright(copyright, type);''')
			licenseconn.commit()
			licensec.close()
			licenseconn.close()

		if options.licenses:
			## Store the comments extracted by Ninka per checksum.
			ninkac.execute('''create table if not exists ninkacomments (sha256 text, license text, version text)''')
			ninkac.execute('''create index if not exists comments_index on ninkacomments(sha256);''')

			ninkaconn.commit()
			ninkac.close()
			ninkaconn.close()
	except Exception, e:
		print >>sys.stderr, e

	c.close()
	conn.close()

	pool = Pool()

	pkgmeta = []
	## TODO: do all kinds of checks here
	for unpackfile in filelist:
		try:
			unpacks = unpackfile.strip().split()
			if len(unpacks) == 3:
				origin = "unknown"
				(package, version, filename) = unpacks
			else:
				(package, version, filename, origin) = unpacks
			pkgmeta.append((options.filedir, package, version, filename, origin, options.db))
		except Exception, e:
			# oops, something went wrong
			print >>sys.stderr, e
	res = filter(lambda x: x != None, pool.map(checkalreadyscanned, pkgmeta, 1))

	oldpackage = ""
	oldres = []
	for i in res:
		try:
			(package, version, filename, origin, filehash) = i
			if filehash in blacklistsha256sums:
				continue
			if options.verify:
				unpack_verify(options.filedir, filename)
			if package != oldpackage:
				oldres = []
			res = unpack_getstrings(options.filedir, package, version, filename, origin, filehash, options.db, cleanup, license, copyrights, pool, options.ninkacomments, options.licensedb, oldpackage, oldres)
			oldres = map(lambda x: x[2], res)
			oldpackage = package
		except Exception, e:
				# oops, something went wrong
				print >>sys.stderr, e

if __name__ == "__main__":
    main(sys.argv)
