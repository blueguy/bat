#!/usr/bin/python

## Binary Analysis Tool
## Copyright 2009-2011 Armijn Hemel for LOCO (LOOHUIS CONSULTING)
## Licensed under Apache 2.0, see LICENSE file for details

import sys, os
import tempfile
import fsmagic

# find a squashfs file system, starting at a certain offset
# Returns the offset of the file system. If a firmware contains
# multiple squashfs file systems it should be applied multiple times
## TODO: possibly also return the type, or possible types of squashfs
## we know of, so we can do a better job at unpacking.
def findSquashfs(data, offset=0):
	marker = -1
	marker = findType('squashfs-le', data,offset)
	if marker == -1:
		return findType('squashfs-be', data, offset)
	else:
		marker2 = findType('squashfs-be', data, offset)
		if marker2 != -1:
			return min(marker, marker2)
		else:
			# just one marker found
			return marker

def findMarker(marker, data, offset=0):
	return data.find(marker, offset)

def findType(type, data, offset=0):
	return data.find(fsmagic.fsmagic[type], offset)

def findCpio(data, offset=0):
	for marker in fsmagic.cpio:
		res = findMarker(marker, data, offset)
		if res != -1:
			return res
	return -1

def findCpioTrailer(data, offset=0):
	res = findMarker('TRAILER!!!', data, offset)
	if res != -1:
		return res
	return -1

def findGzip(data, offset=0):
	return findType('gzip', data, offset)

def findZip(data, offset=0):
	return findType('zip', data, offset)

def findCramfs(data, offset=0):
	return findType('cramfs', data, offset)

def findUbifs(data, offset=0):
	return findType('ubifs', data, offset)

def findRar(data, offset=0):
	return findType('rar', data, offset)

## not reliable according to comments in /usr/share/magic
def findLZMA(data, offset=0):
	return findType('lzma_alone', data, offset)

def findBzip2(data, offset=0):
	return findType('bz2', data, offset)

def markerSearch(data):
	offsets = []
	marker_keys = fsmagic.marker.keys()
	for key in marker_keys:
		res = data.find(fsmagic.marker[key])
		while res != -1:
			offsets.append((res, key))
			res = data.find(fsmagic.marker[key], res+1)
	offsets.sort()
	for i in offsets:
		print hex(i[0]), i[1], i[0]%8

def bruteForceSearch(data):
	offsets = []
	fsmagic_keys = fsmagic.fsmagic.keys()
	for key in fsmagic_keys:
		res = data.find(fsmagic.fsmagic[key])
		while res != -1:
			offsets.append((res, key))
			res = data.find(fsmagic.fsmagic[key], res+1)
	offsets.sort()
	for i in offsets:
		print hex(i[0]), i[1], i[0]%8
