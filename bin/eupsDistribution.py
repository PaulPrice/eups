#!/usr/bin/env python
# -*- python -*-
#
# a class for handling package installation and creation requests; an 
# engine for eups_distrib
#
import sys, os, re, atexit, shutil
import eups
import eupsServer 
from eupsServer import ServerConf, Manifest, TaggedProductList, RemoteFileNotFound
from eupsDistribFactory import DistribFactory
from eupsDistrib import DefaultDistrib, findInstallableRoot

class Distribution(object):
    """an engine for handling package installation and creation requests"""

    def __init__(self, Eups, packageBase, flavor=None, options=None, 
                 distFactory=None, verbosity=0, log=sys.stderr, noclean=False):
        """create a Distribution engine for a given server base URL
        @param Eups          the Eups controller instance to use
        @param packageBase   the base URL for the package server to pull 
                                packages from
        @param flavor        the platform flavor of interest.  When installing
                                packages, this value is ignored and the version
                                set in the Eups controller is assumed to be
                                the target platform.  For all other actions
                                (creating server packages, listing available 
                                packages), this value will be assumed.  If 
                                None or "generic", then a generic platform
                                is assumed. 
        @param options       a dictionary of options to pass to Distrib 
                                instances used to install and create packages
        @param distFactory   a DistFactory instance to use.  If not provided
                                a default one is created.
        @param verbosity     if > 0, print status messages; the higher the 
                               number, the more messages that are printed
                               (default=0).
        @param log           the destination for status messages (default:
                               sys.stderr)
        """
        self.Eups = Eups
        if not flavor:
            flavor = Eups.flavor
        self.flavor = flavor
        self.noclean = noclean
        self.distFactory = distFactory
        self.options = options
        self.verbose = verbosity
        if not isinstance(self.verbose, int):
            self.verbose = 0
        self.log = log
        self.distServer = None
        if self.options is None:
            self.options = {}
        if not isinstance(self.options, dict):
            raise RuntimeError("Non-dictionary passed to options parameter: " +
                               repr(self.options))
        if packageBase:
            override = None
            if self.options.has_key('serverconf'):
                override = options['serverconf']
            self.distServer = ServerConf.makeServer(packageBase, eups=Eups,
                                                    override=override,
                                                    verbosity=self.verbose-1, 
                                                    log=self.log)
        if self.distFactory is None:
            self.distFactory = DistribFactory(self.Eups, self.distServer)
        elif not self.distServer:
            self.distFactory.distServer = self.distServer


    def _mergeOptions(self, override):
        if self.options:
            out = self.options.copy()
        else:
            out = {}
        if isinstance(override, dict):
            for key in override.keys():
                out[key] = self.override[key]
            if len(out.keys()) == 0:
                return None
        return out

    def install(self, product, version=None, asCurrent=None, tag=None, 
                nodepend=False, options=None, manifest=None, distributionSet=None):
        """
        @param product    the name of the product to install
        @param version    the desired version of the product; if not provided,
                            the version associated with the release identified 
                            by the tag parameter (which itself defaults to 
                            "current") will be installed.
        @param tag        if provided, prefer an installation associated with 
                            with this logical name.  In particular, if version
                            is not specified, the version associated with 
                            the tagged release given by this name will be 
                            installed.
        @param asCurrent  if True, any newly installed packages will be marked
                            current.  If None, new installed packages will only
                            be marked current if there are no other versions
                            currently marked current. 
        @param nodepend   if True, the product dependencies will not be installed
        @param options    a dictionary of named options that are used to fine-
                            tune the behavior of this Distrib class.  See 
                            discussion above for a description of the options
                            supported by this implementation; sub-classes may
                            support different ones.
        @param manifest   use this manifest (a local file) as the manifest for 
                            the requested product instead of downloading manifest
                            from the server.
        @param distributionSet list of Distributions to search for product if not found in self
        """
        if self.distServer is None:
            raise RuntimeError("No distribution server set")
        productRoot = self.getInstallRoot()
        if productRoot is None:
            raise RuntimeError("No writable directories available in EUPS_PATH")

        opts = self._mergeOptions(options)

        flavor = self.Eups.flavor
        if version is None:
            info = self.distServer.getTaggedProductInfo(product, flavor, tag)
            version = info[2]
            if not version:
                thetag = tag
                if thetag is None: thetag = "current"
                raise RemoteFileNotFound("No %s version tagged for product %s; please specify a version" %
                                         (thetag, product))
            if self.verbose > 0:
                thetag = tag
                if thetag is None: thetag = "current"
                print >> self.log, "Installing the %s version of %s, %s" % \
                    (thetag, product, version)

        if manifest is not None:
            if not manifest or os.path.exists(manifest):
                raise RuntimeError("%s: user-provided manifest not found")
            man = Manifest.fromFile(manifest, self.Eups, 
                                    verbosity=self.Eups.verbose-1)
            if not product:
                product = man.product
            if not version:
                version = man.version
        else:
            man = self.distServer.getManifest(product, version, flavor,
                                              self.Eups.noaction)

        self._recursiveInstall(0, man, product, version, productRoot, 
                               asCurrent, opts, distributionSet=distributionSet)

    def _recursiveInstall(self, recursionLevel, manifest, product, version, productRoot, 
                          asCurrent=None, opts=None, recurse=True, setups=None, 
                          installed=None, tag=None, ances=None, distributionSet=None):
                          
        if installed is None:
            installed = []
        if setups is None:
            setups = []
        flavor = self.flavor

        idstring = " %s %s for %s" % \
            (manifest.product, manifest.version, flavor)
        #
        # Is it already declared with this tag?
        #
        try:
            self.Eups.findVersion(manifest.product, manifest.version)
            if self.verbose > 0:
                "%s is already declared %s" % (manifest.product, manifest.version)
            return
        except RuntimeError, e: # We didn't find the version, so we'll have to install it
            pass

        products = manifest.getProducts()
        if self.verbose >= 0 and len(products) == 0:
            print >> self.log, "Warning: no installable packages associated", \
                "with", idstring

        for prod in products:
            pver = "%s-%s" % (prod.product, prod.version)
            if pver in installed:
                if not asCurrent:
                    continue
                #
                # Is it already declared with this tag?
                #
                try:
                    self.Eups.findVersion(prod.product, self.Eups.getCurrent())
                    if self.verbose > 0:
                        "%s is already declared %s" % (prod.product, self.Eups.getCurrent())
                    continue
                except RuntimeError, e: # We didn't find a stable version; we'll have to look it up
                    eups.debug("XX", e)
                    pass

            info = self.Eups.listProducts(prod.product, prod.version)

            justDeclare = False         # do we only need to declare this product?
            if len(info) > 0:
                installed.append(pver)
                if recursionLevel == 0:
                    setups.append("setup --keep %s %s" % (prod.product, prod.version))
                if self.verbose >= 0:
                    print >> self.log, \
                        "Required product %s %s is already installed" % \
                        (prod.product, prod.version)

                if asCurrent:       # we need to process dependencies so as to declare them Current()
                    justDeclare = True
                else:
                    continue

            if not recurse or \
                    (prod.product == product and 
                     prod.version == version):

                if justDeclare:
                    pass
                else:
                    if self.verbose >= 0 and prod.product == manifest.product and \
                            prod.version == manifest.version:
                        if self.verbose > 0:
                            print >> self.log, "Dependencies complete; now installing",
                        else:
                            print >> self.log, "Installing",
                        print >> self.log, prod.product, prod.version

                    builddir = self.makeBuildDirFor(productRoot, prod.product,
                                                    prod.version, self.Eups.flavor)
                    # write the distID to the build directory to aid 
                    # clean-up if it fails
                    self._recordDistID(prod.distId, builddir)

                    distrib = \
                        self.distFactory.createDistrib(prod.distId, flavor, 
                                                       tag, opts, self.verbose, 
                                                       self.log)
                    if self.verbose > 1 and 'NAME' in dir(distrib):
                        print >> self.log, "Using Distrib type:", distrib.NAME

                    try:
                        distrib.installPackage(distrib.parseDistID(prod.distId), 
                                               prod.product, prod.version,
                                               productRoot, prod.instDir, setups,
                                               builddir)
                    except eupsServer.RemoteFileNotFound, e:
                        if self.verbose >= 0:
                            print >> self.log, "Failed to install %s %s: %s" % \
                                (prod.product, prod.version, str(e))
                        raise e
                    except RuntimeError, e:
                        raise e

                    if self.verbose >= 0:
                        print >> self.log, \
                            "Package %s %s installed successfully" % \
                            (prod.product, prod.version)

                setups.append("setup --keep %s %s" % (prod.product, prod.version))

                # declare the newly installed package, if necessary
                root = os.path.join(productRoot, self.Eups.flavor, prod.instDir)
                if justDeclare:
                    tablefile = None    # don't try to redeclare product, just make it current
                else:
                    tablefile = prod.tablefile
                    
                try:
                    self.ensureDeclare(prod.product, prod.version, tablefile,
                                       root, productRoot, asCurrent)
                except RuntimeError, e:
                    print >> sys.stderr, e
                    continue
                
                installed.append(pver)

                # write the distID to the installdir/ups directory to aid 
                # clean-up
                self._recordDistID(prod.distId, root)

                # clean up the build directory
                if self.noclean:
                    if self.verbose:
                        print >> sys.stderr, "Not removing the build directory %s; you can cleanup manually with \"eups distrib clean\"" % (self.getBuildDirFor(self.getInstallRoot(), prod.product, prod.version))
                else:
                    self.clean(prod.product, prod.version)

            else:
                # We may still need to declare the product
                if justDeclare:
                    try:
                        self.ensureDeclare(prod.product, prod.version, asCurrent=True)
                    except RuntimeError, e:
                        print >> sys.stderr, e

                # get the manifest for each dependency and install it 
                # recursively
                if self.verbose > 0:
                    if justDeclare:
                        print >> self.log, "Declaring %s %s and its dependencies %s" % \
                              (prod.product, prod.version, self.Eups.getCurrent().tag)
                    else:
                        print >> self.log, "Installing %s %s and its dependencies" % (prod.product, prod.version)

                if ances is None: 
                    ances = [ "%s-%s" % (manifest.product, manifest.version) ]
                if pver in ances:
                    if self.verbose >= 0:
                        print >> self.log, "Detected circular dependencies", \
                            "within manifest for %s; short-circuiting." %  \
                            idstring 
                        if self.verbose > 2:
                            print >> self.log, "Package installation already",\
                                "in progress:"
                            for a in ances:
                                print >> self.log, "\t", a
                    continue
                ances.append(pver)
                #
                # Find the server that provides the desired product
                #
                if distributionSet:
                    dist = distributionSet.lookup(prod.product, prod.version, flavor)
                else:
                    dist = None

                if not dist:
                    dist = self

                nextman = dist.distServer.getManifest(prod.product, prod.version, 
                                                      flavor, self.Eups.noaction)
                dist._recursiveInstall(recursionLevel + 1, nextman, prod.product, prod.version, 
                                       productRoot, asCurrent, opts, True, 
                                       setups, installed, tag, ances, distributionSet=distributionSet)

    def getBuildDirFor(self, productRoot, product, version, flavor=None):
        """return a recommended directory to use to build a given product.
        In this implementation, the returned path will usually be of the form
        <productRoot>/<buildDir>/<flavor>/<product>-<root> where buildDir is, 
        by default, "EupsBuildDir".  buildDir can be overridden at construction
        time by passing a "buildDir" option.  If the value of this option
        is an absolute path, then the returned path will be of the form
        <buildDir>/<flavor>/<product>-<root>.

        @param productRoot    the root directory where products are installed
        @param product        the name of the product being built
        @param version        the product's version 
        @param flavor         the product flavor.  If None, assume the current 
                                default flavor
        """
        buildRoot = "EupsBuildDir"
        if self.options.has_key('buildDir'):  
            buildRoot = self.options['buildDir']
        if not flavor:  flavor = self.Eups.flavor

        pdir = "%s-%s" % (product, version)
        if os.path.isabs(buildRoot):
            return os.path.join(buildRoot, flavor, pdir)
        return os.path.join(productRoot, buildRoot, flavor, pdir)

    def makeBuildDirFor(self, productRoot, product, version, flavor=None):
        """create a directory for building the given product.  This calls
        getBuildDirFor(), ensures that the directory exists, and returns 
        the path.  
        @param productRoot    the root directory where products are installed
        @param product        the name of the product being built
        @param version        the product's version 
        @param flavor         the product flavor.  If None, assume the current 
                                default flavor
        @exception OSError  if the directory creation fails
        """
        dir = self.getBuildDirFor(productRoot, product, version, flavor)
        if not os.path.exists(dir):
            os.makedirs(dir)
        return dir

    def cleanBuildDirFor(self, productRoot, product, version, force=False, 
                         flavor=None):
        """Clean out the build directory used to build a product.  This 
        implementation calls getBuildDirFor() to get the full path of the 
        directory used; then, if it exists, the directory is removed.  As 
        precaution, this implementation will only remove the directory if
        it appears to be below the product root, unless force=True.

        @param productRoot    the root directory where products are installed
        @param product        the name of the built product
        @param version        the product's version 
        @param force          override the removal restrictions
        @param flavor         the product flavor.  If None, assume the current 
                                default flavor
        """
        dir = self.getBuildDirFor(productRoot, product, version, flavor)
        if os.path.exists(dir):
            if force or (len(productRoot) > 0 and dir.startswith(productRoot) 
                         and len(dir) > len(productRoot)+1):
                if self.verbose > 1: 
                    print >> self.log, "removing", dir
                eupsServer.system("rm -rf " + dir,
                                  verbosity=self.verbose-1, log=self.log)
            elif self.verbose > 0:
                print >> self.log, "%s: not under root (%s); won't delete unless forced (use --force)" % (dir, productRoot)


    def clean(self, product, version, flavor=None, uninstall=False):
        """clean up the remaining remants of the failed installation of 
        a distribution.  
        @param product      the name of the product to clean up after
        @param version      the version of the product
        @param flavor       the flavor for the product to assume.  This affects
                               where we look for partially installed packages.
                               None (the default) means the default flavor.
        @parma uninstall    if True, run the equivalent of "eups remove" for 
                               this package. default: False.
        """
        handlePartialInstalls = True
        productRoot = self.getInstallRoot()

        # check the build directory
        buildDir = self.getBuildDirFor(productRoot, product, version, flavor)
        if self.verbose > 0:
            print >> self.log, "Looking for build directory:", buildDir

        if os.path.exists(buildDir):
            distidfile = os.path.join(buildDir, "distID.txt")
            if os.path.isfile(distidfile):
                distId = self._readDistIDFile(distidfile)
                if distId:
                    if self.verbose > 1:
                        print >> self.log, "Attempting distClean for", \
                            "build directory via ", distId
                    self.distribClean(product, version, distId, flavor)

            self.cleanBuildDirFor(productRoot, product, version, flavor)

        # now look for a partially installed (but not yet eups-declared) package
        if handlePartialInstalls and self.distServer and flavor == self.Eups.flavor:
            if self.verbose > 1:
                print >> self.log, "Looking for a partially installed package:",\
                    product, version

            man = None
            try:
                man = self.distServer.getManifest(product, version, flavor,
                                                  self.Eups.noaction)
            except RemoteFileNotFound, e:
                # we'll skip this part of the clean up
                pass

            if man:
                installDir = map(lambda x: x.instDir, 
                                 filter(lambda y: y.product == product and y.version == version,
                                        man.getProducts()))

                if installDir and os.path.isdir(installDir[0]):
                    distidfile = os.path.join(installDir[0], "ups", "distID.txt")
                    if os.path.isfile(distidfile):
                        distId = self._readDistIDFile(distidfile)
                        if distId:
                            if self.verbose > 1:
                                print >> self.log, "Attempting distClean for", \
                                    "installation directory via ", distId
                            self.distribClean(product, version, distId, flavor)
                    
                    # make sure this directory is not declared for any product
                    installDirs = map(lambda x: x.productDir, self.Eups.listProducts())
                    if installDir[0] not in installDirs:
                        if self.verbose > 0:
                            print >> self.log, "Removing installation dir:", \
                                installDir[0]
                        eupsServer.system("/bin/rm -rf %s" % installDir[0])
                        
        # now see what's been installed
        if uninstall and flavor == self.Eups.flavor:
            info = None
            distidfile = None
            try:
                info = self.Eups.listProducts(product, version)[0]
            except IndexError, e:
                pass
            if info:
                # clean up anything associated with the successfully 
                # installed package
                distidfile = os.path.join(info.productDir, "ups", "distID.txt")
                if os.path.isfile(distidfile):
                    distId = self._readDistIDFile(distidfile)
                    if distId:
                        self.distribClean(product, version, distId, flavor)

                # now remove the package
                if self.verbose >= 0:
                    print >> self.log, "Uninstalling", product, version
                self.Eups.remove(product, version, False)


    def distribClean(self, product, version, distId, flavor=None):
        """attempt to do a distrib-specific clean-up based on a distribID.
        @param product      the name of the product to clean up after
        @param version      the version of the product
        @param flavor       the flavor for the product to assume.  This affects
                               where we look for partially installed packages.
                               None (the default) means the default flavor.
        @param distId       the distribution ID used to install the package.
        """
        if not flavor:  flavor = self.flavor
        distrib = self.distFactory.createDistrib(distId, flavor,
                                                 options=self.options, 
                                                 verbosity=self.verbose, 
                                                 log=self.log)
        location = distrib.parseDistID(distId)
        productRoot = self.getInstallRoot()
        return distrib.cleanPackage(product, version, productRoot, location)


    def getInstallRoot(self):
        """return the first directory in the eups path that the user can install 
        stuff into
        """
        return findInstallableRoot(self.Eups)

    def _recordDistID(self, distId, installDir):
        ups = os.path.join(installDir, "ups")
        file = os.path.join(ups, "distID.txt")
        if os.path.isdir(ups):
            try:
                fd = open(file, 'w')
                try:
                    print >> fd, distId
                finally:
                    fd.close()
            except:
                if self.verbose >= 0:
                    print >> self.log, "Warning: Failed to write distID to %s: %s" (file, traceback.format_exc(0))

    def _readDistIDFile(self, file):
        distId = None
        idf = open(file)
        try:
            for distId in idf:
                distId = distId.strip()
                if len(distId) > 0:
                    break
            idf.close()
        except Exception, e:
            if self.verbose >= 0:
                print >> self.log, "Warning: trouble reading %s, skipping" % file

        return distId
            

    def ensureDeclare(self, product, version, tablefileloc=None, rootdir=None, 
                      productRoot=None, asCurrent=None):
        
        flavor = self.Eups.flavor

        # discover if the product has been declared.  Note that we can't 
        # use listProducts(productName, versionName) as the version list was 
        # read before installPackage was run, so look for the version file 
        # directly 
        dodeclare = unknown = False
        try:
            self.Eups.findVersion(product, version, allowNewer=False)
        except RuntimeError, e:
            dodeclare = unknown = True

        try:
            if self.Eups.findCurrentVersion(product)[1] != version and asCurrent:
                dodeclare = True
        except IndexError, e:
            dodeclare = True
            if asCurrent is None:  asCurrent = self.Eups.getCurrent()
        except RuntimeError, e:
            dodeclare = True
            if asCurrent is None:
                asCurrent = self.Eups.getCurrent()

        if not dodeclare:
            return

        if rootdir and not os.path.exists(rootdir):
            msg = "%s %s installation not found at %s" % \
                (product, version, rootdir)
            raise RuntimeError(msg)

        # make sure we have a table file if we need it
        if unknown:
            if tablefileloc == "none":
                tablefile = "none"
            else:
                upsdir = os.path.join(rootdir,'ups')
                tablefile = os.path.join(upsdir, product + ".table")

                if rootdir == "/dev/null":
                    tablefile = self.distServer.getFileForProduct(tablefileloc, product, 
                                                                  version, flavor)
                    tablefile = open(tablefile, "r")
                else:
                    if not os.path.exists(tablefile):
                        if not os.path.exists(upsdir):
                            os.makedirs(upsdir)
                        self.distServer.getFileForProduct(tablefileloc, product, 
                                                          version, flavor,
                                                          filename=tablefile)
                    if not os.path.exists(tablefile):
                        raise RuntimeError("Failed to find table file %s" % tablefile)
        else:
            tablefile = None
            
        if tablefile and tablefile != "none" and not isinstance(tablefile, file):
            if not os.path.exists(tablefile):
                tablefile = tablefileloc

        self.Eups.declare(product, version, rootdir, eupsPathDir=productRoot, 
                          tablefile=tablefile, declareCurrent=asCurrent)
                          

    def listPackages(self, product=None, version=None, tag=None):
        """return a list of available packages for the current platform flavor.
        Each item in the returned list will be a list of the form 
        (product, version, flavor).
        @param product    if provided, the list will be restricted to products
                             with this name
        @param version    if provided, the list will be restricted to products
                             with this version
        @param tag        restrict the list to the tagged release with this 
                             name
        """
        if self.distServer is None:
            raise RuntimeError("No distribution server set")
        return self.distServer.listAvailableProducts(product, version, self.flavor, tag)

    def create(self, serverRoot, distribTypeName, product, version, tag=None, 
               nodepend=False, options=None, manifest=None, distributionSet=None, packageId=None):
        """create and all necessary files for making a particular package
        available and deploy them into a local server directory.  This creates
        not only the requested product but also all of its dependencies unless
        nodepends is True.  Unless Eups.force is True, it will not recreate the 
        a package that is already deployed under the serverRoot directory.
        @param serverRoot   the root directory of a local server distribution
                              tree
        @param distribTypeName     the name of the distribution type to create.  The
                              recognized names are those registered to the 
                              DistribFactory passed to this Distribution's
                              constructor.  Names recognized by default include
                              "builder", "pacman", and "tarball".
        @param product      the name of the product to create
        @param version      the version of the product to create
        @param tag          if not None, update (or create) the tagged release
                              list for this tag name.  Only the information 
                              for the given product will be added/updated.  
                              (Default: True)
        @param nodepend     if True, only the requested product package will be 
                              created.  The product dependencies will be skipped.
                              (Default: False)
        @param manifest     an existing manifest filename; if provided, this 
                              will be used as the list of dependencies to assume
                              for this product, rather than generating the 
                              list from the EUPS database.  The deployed manifest
                              will be a modified version in that the distIDs for
                              undeployed packages will be updated and, if 
                              necessary, an entry will be added for the top
                              product (specified by the inputs to this function).
                              Note that this implementation will (unless 
                              nodepend is True) consult the remote server to 
                              determine if the package is available with the 
                              given distID.
        @param distributionSet list of Distributions to search for product if not found in self
        @param packageId     name:version for distribution; default product:version (either field may be omitted)
        """
        opts = self._mergeOptions(options)

        try:
            distrib = \
                self.distFactory.createDistribByName(distribTypeName, 
                                                     options=opts, flavor=self.flavor,
                                                     verbosity=self.verbose)
        except KeyError:
            distrib = None
        if distrib is None:
            raise RuntimeError("%s: Distrib name not recognized" % distribTypeName)

        # load manifest data
        if manifest is None:
            # create it from what we (eups) know about it
            man = distrib.createDependencies(product, version, self.flavor)
        else:
            # load it from the given file
            man = Manifest.fromFile(manifest, self.Eups, self.Eups.verbose-1)

        # we will always overwrite the top package
        id = distrib.createPackage(serverRoot, product, version, self.flavor, overwrite=True)
        #
        # Any products in the top-level table file will be considered current for
        # the purposes of creating this distribution
        #
        for p in man.getProducts():
            self.Eups.declareCurrent(p.product, p.version, local=True)

        if not nodepend:
            created = [ "%s-%s" % (product, version) ]
            self._recursiveCreate(serverRoot, distrib, man, created, True, distributionSet)

        # update the manifest record for the requested product
        dp = man.getDependency(product, version)
        if dp is None:
            # this product is not found in the manifest; this might happen if 
            # this function was passed a manifest file to use.  Just in case,
            # check the auto-generated manifest for a record and add it to
            # the given one
            tdp = distrib.createDependencies(product, version, self.flavor)
            tdp = template.getDependency(product, version)
            if template is not None:
               man.getProducts().append(tdp) 
        else:
            dp.distId = id

        # deploy the manifest file
        if packageId:
            vals = packageId.split(":")
            if len(vals) != 2:
                raise RuntimeError, ("Expected package Id of form name:version, saw \"%s\"" % packageId)
            if vals[0] == "":
                vals[0] = product
            if vals[1] == "":
                vals[1] = version
                
            packageName, packageVersion = vals
        else:
            packageName = product
            packageVersion = version

        distrib.writeManifest(serverRoot, man.getProducts(), packageName, packageVersion,
                              self.flavor, self.Eups.force)
        
    def _recursiveCreate(self, serverRoot, distrib, manifest, created=None, 
                         recurse=True, distributionSet=None):
        if created is None: 
            created = []

        for dp in manifest.getProducts():
            pver = "%s-%s" % (dp.product, dp.version)
            if pver in created:
                continue

            # check to see if it looks like it is available in the format
            # given in the file
            if distrib.parseDistID(dp.distId) is None:
                # this may happen if create() was handed a manifest file
                if _availableAtLocation(dp):
                    continue
            else:
                flavor = dp.flavor
                if dp.flavor == "generic":   flavor = None
                if distrib.packageCreated(serverRoot, dp.product, dp.version, 
                                          flavor):
                    if not self.Eups.force:
                        if self.verbose > 0:
                            print >> self.log, "Dependency %s %s already deployed; skipping" % (dp.product, dp.version)
                        created.append(pver)
                        continue

                    elif self.verbose > 0:
                        print >> self.log, "Overwriting existing dependency,", dp.product, dp.version
                        
            #
            # Check if this product is available elsewhere
            #
            if distributionSet and not self.Eups.force:
                already_available = False # have we discovered that it's available from a server?
                for (pkgroot, pkgs) in distributionSet.pkgList:
                    if already_available:
                        break

                    for (p, v, f) in pkgs:
                        if (dp.product, dp.version) == (p, v):
                            if self.verbose > 0:
                                print >> self.log, "Dependency %s %s is already available from %s; skipping" % \
                                      (dp.product, dp.version, pkgroot)
                            already_available = True
                            break

                if already_available:
                    created.append(pver)
                    continue

            # we now should attempt to create this package because it appears 
            # not to be available
            man = distrib.createDependencies(dp.product, dp.version, self.flavor)

            id = distrib.createPackage(serverRoot, dp.product, dp.version, 
                                       self.flavor)
            created.append(pver)
            dp.distId = id
                
            if recurse:
                self._recursiveCreate(serverRoot, distrib, man, created, recurse, distributionSet)

            distrib.writeManifest(serverRoot, man.getProducts(), dp.product,
                                  dp.version, self.flavor, self.Eups.force)

    def _availableAtLocation(self, dp, serverRoot):
        distrib = self.distFactory.createDistrib(dp.distId, dp.flavor, None,
                                                 self.options, self.verbose-2,
                                                 self.log)
        flavor = dp.flavor
        if flavor == generic:  flavor = None
        return distrib.packageCreated(serverRoot, dp.product, dp.version, flavor)

    def createTaggedRelease(self, serverRoot, tag, product, version=None, 
                            flavor=None, distrib=None):
        """create and release a named collection of products based on the 
        known dependencies of a given product.  
        @param serverRoot   the root directory of a local server distribution
                              tree
        @param tag          the name to give to this tagged release.  
        @param product      the name of the product to create
        @param version      the version of the product to create.  (Default:
                               the version marked current in the EUPS db)
        @param flavor       the flavor to associate with this release (Default:
                               "generic")
        @param distrib      a Distrib instance to use to determine which 
                              products to include.  If not provided, a default 
                              will be used.  
        """
        if distrib is not None and not isinstance(distrib, eupsDistrib.Distrib):
            raise TypeError("distrib parameter not a Distrib instance")
        validTags = self.getRecommendedTags(serverRoot)
        if not self.Eups.force and tag not in validTags:
            raise RuntimeError("tag %s not amoung recommended tag names (%s)" %
                               (tag, ", ".join(validTags)))

        if not flavor:  flavor = "generic"

        if not version:
            version = self.Eups.findCurrentVersion(product)[1]

        if distribTypeName:
            distrib = \
                self.distFactory.createDistribByName(distribTypeName, 
                                                     options=self.options,
                                                     verbosity=self.verbose,
                                                     log=self.log)
        else:
            distrib = DefaultDistrib(self.Eups, self.distServer, self.flavor, 
                                     options=self.options, 
                                     verbosity=self.verbose,
                                     log=self.log)

        release = distrib.createTaggedRelease(serverRoot, tag, product, version,
                                              flavor)
        distrib.writeTaggedRelease(serverRoot, tag, products, flavor, 
                                   self.Eups.flavor)

    def updateTaggedRelease(self, serverRoot, tag, product, version, 
                            flavor="generic", info=None, distrib=None):
        """update/add the version for a given product in a tagged release
        @param serverRoot   the root directory of a local server distribution
                              tree
        @param tag          the name to give to this tagged release.  
        @param product      the name of the product to create
        @param version      the version of the product to create.  (Default:
                               the version marked current in the EUPS db)
        @param flavor       the flavor to associate with this release (Default:
                               "generic")
        @param info         an optional list containing extra data to associate
                               with the product in the release.
        @param distrib      a Distrib instance to use to access tag release
                              information.  If not provided, a default will be 
                              used.  
        """
        if distrib is not None and not isinstance(distrib, eupsDistrib.Distrib):
            raise TypeError("distrib parameter not a Distrib instance")
        validTags = self.getRecommendedTags(serverRoot)
        if not self.Eups.force and tag not in validTags:
            raise RuntimeError("tag %s not amoung recommended tag names (%s)" %
                               (tag, ", ".join(validTags)))

        if distrib is None:
            distrib = DefaultDistrib(self.Eups, self.distServer, self.flavor, 
                                     options=self.options, 
                                     verbosity=self.verbose)

        pl = distrib.getTaggedRelease(serverRoot, tag, flavor)
        if pl is None:
            pl = TaggedProductList(tag, flavor)

        pl.addProduct(product, version, flavor)
        distrib.writeTaggedRelease(serverRoot, tag, pl, flavor, True);
            

    def getRecommendedTags(self, serverRoot):
        """return a list of recommended tag names for the given server.
        This will look for a file under the server root directory called
        "tags.txt" containing a space/newline delimited list of names.
        If the file does not exist, the values recommended by eups 
        will be returned.
        @param serverRoot   the root directory where releases are installed.
        """
        out = None
        tagnames = os.path.join(serverRoot, "tags.txt")
        if os.path.exists(tagnames):
            names = ""
            try:
                fd = open(tagnames)
                names = fd.read()

                out = re.split("\s+", names)
                fd.close()
            except IOError, e:
                if self.verbose >= 0:
                    print >> self.log, \
                        "Problem reading %s: %s; using defaults" % \
                        (tagnames, str(e))

        if out is None:
            out = eups.getValidTags()

        return out

    def clearServerCache(self):
        if self.distServer:
            self.distServer.clearConfigCache()

#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-

class DistributionSet(object):
    """A set of Distributions to be searched for the desired Distribution and thence product"""

    def __init__(self, Eups, pkgroots, dopts={}, installFlavor=None, distribClasses=None, tag=None):
        if len(pkgroots) == 0:
            raise RuntimeError, ("No package servers to query; set -r or $EUPS_PKGROOT")

        if not distribClasses:
            distribClasses = {}

        self.pkgroots = []                   # Pkgroots that we know about (a list as we care about the order)
        self.distributions = {}              # (Server, Distribution) that correspond to the pkgroots
        self.pkgList = []                    # list of provided packages
        self.primary = {}                    # is this pkgroot primary?

        primary = "primary"
        for pkgroot in pkgroots:
            if pkgroot == None:
                ds = None
            else:
                ds = ServerConf.makeServer(pkgroot, eups=Eups, verbosity=Eups.verbose)

            df = DistribFactory(Eups, ds)

            for name in distribClasses.keys():
                df.register(distribClasses[name], name)

            dist = Distribution(Eups, pkgroot, options=dopts, flavor=installFlavor,
                                distFactory=df, verbosity=Eups.verbose, noclean=dopts.get("noclean"))

            self.pkgroots += [pkgroot]
            self.distributions[pkgroot] = dist

            try:
                packages = dist.listPackages(tag=tag)
            except RemoteFileNotFound:
                packages = [(None, None, None)]

            def sort_by_name_then_version_then_flavor(a, b):
                """Sort by name, then version, then flavor"""
                if a[0] != b[0]:
                    return cmp(a[0], b[0])

                vcmp = eups.version_cmp(a[1], b[1])

                if vcmp:
                    return vcmp
                else:
                    return cmp(a[2], b[2])

            packages.sort(sort_by_name_then_version_then_flavor)

            self.pkgList += [(pkgroot, packages)]
            
            self.primary[pkgroot] = primary

            primary = "secondary"
    
    def listPackages(self, productName, versionName):
        """Return a list of tuples (pkgroot, package-list)"""

        if not productName and not versionName: # they want everything
            return self.pkgList

        pkgList = []
        for (pkgroot, pkgs) in self.pkgList:
            our_pkgs = []
            for (name, version, flav) in pkgs:
                if productName and productName != name:
                    continue
                if versionName and versionName != version:
                    continue

                our_pkgs += [(name, version, flav)]
                
            pkgList += [(pkgroot, our_pkgs)]

        return pkgList

    def lookup(self, productName, versionName, flavor):
        """Lookup the Distribution providing (productName, versionName, flavor)"""

        for (pkgroot, pkgs) in self.pkgList:
            for (name, version, flav) in pkgs:
                if name == productName and version == versionName:
                    if flavor and flav != "generic" and flavor != flav:
                        continue

                    return self.distributions[pkgroot]

        return None