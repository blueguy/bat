#!/usr/bin/python

## Binary Analysis Tool
## Copyright 2011-2012 Armijn Hemel for Tjaldur Software Governance Solutions
## Licensed under Apache 2.0, see LICENSE file for details

'''
This module contains helper functions that are run before any of the other
scans.
'''

import sys, os, subprocess, os.path, shutil, stat
import tempfile, re, magic
import fsmagic, fssearch, extractor

## method to search for all the markers in magicscans
def genericMarkerSearch(filename, magicscans, envvars=None):
	datafile = open(filename, 'rb')
	databuffer = []
	offsets = {}
	offset = 0
	datafile.seek(offset)
	databuffer = datafile.read(100000)
        marker_keys = magicscans
	for key in marker_keys:
		offsets[key] = []
	while databuffer != '':
		for key in marker_keys:
			res = databuffer.find(fsmagic.fsmagic[key])
			if res == -1:
				continue
			else:
				while res != -1:
					## we should return this differently, so we can sort per offset and
					## do a possibly better scan
					#offsets[key].append((offset + res, key))
					offsets[key].append(offset + res)
					res = databuffer.find(fsmagic.fsmagic[key], res+1)
		## move the offset 99950
		datafile.seek(offset + 99950)
		## read 100000 bytes with a 50 bytes overlap
		## overlap with the previous read
		databuffer = datafile.read(100000)
		if len(databuffer) >= 50:
			offset = offset + 99950
		else:
			offset = offset + len(databuffer)
	datafile.close()
	return offsets

## XML files actually only need to be verified and tagged so other scans can decide to ignore it
def searchXML(filename, tempdir=None, tags=[], offsets={}, envvars=None):
	newtags = []
	p = subprocess.Popen(['xmllint','--noout', filename], stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=True)
	(stanout, stanerr) = p.communicate()
	if p.returncode == 0:
		newtags.append("xml")
	return ([], newtags)

## method to verify if a file only contains text
## Since the default encoding in Python 2 is 'ascii' and we can't guarantee
## that it has been set by the user to something else this will not work
## on UTF-8 encoded files, unless we ask the user to set the encoding in
## site.py which we can't.
##
## Interesting link with background info:
## * http://fedoraproject.org/wiki/Features/PythonEncodingUsesSystemLocale
def verifyText(filename, tempdir=None, tags=[], offsets={}, envvars=None):
	newtags = []
	datafile = open(filename, 'rb')
	databuffer = []
	offset = 0
	datafile.seek(offset)
	databuffer = datafile.read(100000)
	while databuffer != '':
		if not extractor.isPrintables(databuffer):
			datafile.close()
			newtags.append("binary")
			return ([], newtags)
		## move the offset 100000
		datafile.seek(offset + 100000)
		databuffer = datafile.read(100000)
		offset = offset + len(databuffer)
	newtags.append("text")
	datafile.close()
	return ([], newtags)

## quick check to verify if a file is a graphics file.
def verifyGraphics(filename, tempdir=None, tags=[], offsets={}, envvars=None):
	newtags = []
	if "text" in tags or "compressed" in tags:
		return ([], newtags)
	newtags = verifyJPEG(filename, tempdir, tags, offsets, envvars)[1]
	if newtags == []:
		newtags = verifyBMP(filename, tempdir, tags, offsets, envvars)[1]
	return ([], newtags)

def verifyBMP(filename, tempdir=None, tags=[], offsets={}, envvars=None):
	newtags = []
	p = subprocess.Popen(['bmptopnm', filename], stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=True)
	(stanout, stanerr) = p.communicate()
	if p.returncode != 0 or "warning" in stanerr:
		return ([], newtags)
	newtags.append("bmp")
	newtags.append("graphics")
	return ([], newtags)

def verifyJPEG(filename, tempdir=None, tags=[], offsets={}, envvars=None):
	newtags = []
	p = subprocess.Popen(['jpegtopnm', '-multiple', filename], stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=True)
	(stanout, stanerr) = p.communicate()
	if p.returncode != 0:
		return ([], newtags)
	## multiple jpegs in this file, so we need to unpack
	if len(stanerr.strip().split("\n")) > 1:
		return ([], newtags)
	newtags.append("jpeg")
	newtags.append("graphics")
	return ([], newtags)

def verifyGzip(filename, tempdir=None, tags=[], offsets={}, envvars=None):
	newtags = []
	if "text" in tags or "graphics" in tags:
		return ([], newtags)
	if not 0 in offsets['gzip']:
		return ([], newtags)
	p = subprocess.Popen(['gunzip', '-t', filename], stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=True)
	(stanout, stanerr) = p.communicate()
	if p.returncode != 0:
		return ([], newtags)
	## possibly multiple gzips in this file, or bzip2 with trailing data
	if "trailing garbage ignored" in stanerr:
		return ([], newtags)
	## the file contains one or more gzip archives
	newtags.append("gzip")
	newtags.append("compressed")
	return ([], newtags)

def verifyBZ2(filename, tempdir=None, tags=[], offsets={}, envvars=None):
	newtags = []
	if "text" in tags or "graphics" in tags:
		return ([], newtags)
	if not 0 in offsets['bz2']:
		return ([], newtags)
	p = subprocess.Popen(['bunzip2', '-tvv', filename], stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=True)
	(stanout, stanerr) = p.communicate()
	if p.returncode != 0:
		return ([], newtags)
	## possibly multiple bzip2 in this file, or bzip2 with trailing data
	if len(stanerr.strip().split("\n")) > 1:
		if "trailing garbage after EOF ignored" in stanerr:
			return ([], newtags)
		else:
			## output would look like:
			## $ bunzip2 -tvv foo.bz2 
			##  foo.bz2: 
			##    [1: huff+mtf rt+rld]
			##    ok
			## so splitting it on "\n" would give us a list of length 3 in this case
			## perhaps more in other cases. More bzip2 files concatenated would mean
			## that the length of stanerr would be significantly more than the number
			## of the last block that it reports.
			stanerrlines = stanerr.strip().split("\n")
			try:
				blocks = int(stanerrlines[-2].split(':')[0][5:])
				if blocks != (len(stanerrlines) - 2):
					return ([], newtags)
			except:
				return ([], newtags)
	newtags.append("bz2")
	newtags.append("compressed")
	return ([], newtags)
