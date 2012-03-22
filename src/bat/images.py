#!/usr/bin/python

## Binary Analysis Tool
## Copyright 2012 Armijn Hemel for Tjaldur Software Governance Solutions
## Licensed under Apache 2.0, see LICENSE file for details

'''
This is a plugin for the Binary Analysis Tool. It generates images of files, both
full files and thumbnails. The files can be used for informational purposes, such
as detecting roughly where offsets can be found, if data is compressed or encrypted,
etc.

It also generates histograms, which show how different byte values are distributed.
This can provide another visual clue about how files are constructed. Binaries from
the same type (like ELF binaries) are actually quite similar, so binaries that
significantly deviate from this could mean something interesting.

This should be run as a postrun scan
'''

import os, os.path, sys, subprocess, array, cPickle, tempfile
from PIL import Image

def generateImages(filename, unpackreport, leafscans, scantempdir, toplevelscandir, envvars={}):
	if not unpackreport.has_key('sha256'):
		return
	scanenv = os.environ.copy()
	if envvars != None:
		for en in envvars.split(':'):
			try:
				(envname, envvalue) = en.split('=')
				scanenv[envname] = envvalue
			except Exception, e:
				pass

	## TODO: check if BAT_IMAGEDIR exists
	imagedir = scanenv.get('BAT_IMAGEDIR', "%s/%s" % (toplevelscandir, "images"))
	try:
		os.stat(imagedir)
	except:
		## BAT_IMAGEDIR does not exist
		try:
			os.makedirs(imagedir)
		except Exception, e:
			return

	fwfile = open("%s/%s" % (scantempdir, filename))

	## this is very inefficient for large files, but we *really* need all the data :-(
	fwdata = fwfile.read()
	fwfile.close()

	fwlen = len(fwdata)

	if fwlen > 512:
		height = 512
	else:
		height = fwlen
	width = fwlen/height

	## we might need to add some bytes so we can create a valid picture
	if fwlen%height > 0:
		width = width + 1
		for i in range(0, height - (fwlen%height)):
			fwdata = fwdata + chr(0)

	imgbuffer = buffer(bytearray(fwdata))

	im = Image.frombuffer("L", (height, width), imgbuffer, "raw", "L", 0, 1)
	im.save("%s/%s.png" % (imagedir, unpackreport['sha256']))
	if width > 100:
		imthumb = im.thumbnail((height/4, width/4))
		im.save("%s/%s-thumbnail.png" % (imagedir, unpackreport['sha256']))

	'''
	## generate histogram
	p = subprocess.Popen(['python', '/home/armijn/gpltool/trunk/bat-extratools/bat-visualisation/bat-generate-histogram.py', '-i', "%s/%s" % (scantempdir, filename), '-o', '%s/%s-histogram.png' % (imagedir, unpackreport['sha256'])], stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=True)
	(stanout, stanerr) = p.communicate()
	if p.returncode != 0:
		print >>sys.stderr, stanerr
	'''

	## generate piechart and version information
	for i in leafscans:
		if i.keys()[0] == 'ranking':
			if i['ranking']['reports'] != []:
				pickledata = []
				for j in i['ranking']['reports']:
					pickledata.append((j[1], j[3]))
				tmppickle = tempfile.mkstemp()
				cPickle.dump(pickledata, os.fdopen(tmppickle[0], 'w'))
				p = subprocess.Popen(['python', '/home/armijn/gpltool/trunk/bat-extratools/bat-visualisation/bat-generate-piecharts.py', '-i', tmppickle[1], '-o', '%s/%s-piechart.png' % (imagedir, unpackreport['sha256'])], stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=True)
				(stanout, stanerr) = p.communicate()
				if p.returncode != 0:
					print >>sys.stderr, stanerr
				os.unlink(tmppickle[1])
				## do the same for version information
				for j in i['ranking']['reports']:
					if j[4] != {}:
						tmppickle = tempfile.mkstemp()
						pickledata = []
						j_sorted = sorted(j[4], key=lambda x: j[4][x])
						for v in j_sorted:
							pickledata.append((v, j[4][v]))
						cPickle.dump(pickledata, os.fdopen(tmppickle[0], 'w'))
						p = subprocess.Popen(['python', '/home/armijn/gpltool/trunk/bat-extratools/bat-visualisation/bat-generate-version-chart.py', '-i', tmppickle[1], '-o', '%s/%s-%s-version.png' % (imagedir, unpackreport['sha256'], j[1])], stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=True)
						(stanout, stanerr) = p.communicate()
						if p.returncode != 0:
							print >>sys.stderr, stanerr
						os.unlink(tmppickle[1])
