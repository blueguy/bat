#!/usr/bin/python

## Binary Analysis Tool
## Copyright 2011-2012 Armijn Hemel for Tjaldur Software Governance Solutions
## Licensed under Apache 2.0, see LICENSE file for details

'''
Helper script to verify the LIST files generated by generatelist.py. This is useful to see if any typos were made.
'''

import sys, os, os.path
from optparse import OptionParser

def main(argv):
	parser = OptionParser()
	parser.add_option("-f", "--filedir", action="store", dest="filedir", help="path to directory containing files to unpack", metavar="DIR")
	(options, args) = parser.parse_args()

	try:
		filelist = open(options.filedir + "/LIST").readlines()
	except:
		parser.error("'LIST' not found in file dir")

	for unpackfile in filelist:
		try:
			unpacks = unpackfile.strip().split()
			if len(unpacks) != 4:
				print >>sys.stderr, "FORMAT ERROR", unpackfile
				sys.stderr.flush()
		except Exception, e:
			# oops, something went wrong
			print >>sys.stderr, e

if __name__ == "__main__":
	main(sys.argv)
