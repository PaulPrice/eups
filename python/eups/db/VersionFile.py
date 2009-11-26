import os, re, sys, pwd
from eups.Product import Product
from eups.exceptions import ProductNotFound
from eups.utils import ctimeTZ, isRealFilename

var_prod_dir_re = re.compile("\$PROD_DIR")
var_ups_dir_re = re.compile("\$UPS_DIR")
who = re.sub(r",.*", "", pwd.getpwuid(os.getuid())[4])
if who:
    who += " (%s)" % os.getlogin()
else:
    who = os.getlogin()
defaultProductUpsDir = "ups"

class VersionFile(object):
    """
    A representation of the declaration information stored in a version 
    file for a particular product declared in an EUPS database.

    A version file contains the product data for all declared flavors of a 
    product.  That is, a version file is characterized by it product name
    and version name.   For each declared flavor, the following data are 
    stored:
      ups_dir:  the default directory containing the table file.
      table_file:  the full path to the table file
      productDir:  the installation directory
      declarer:  the name of the user that declared the product
      declared:  a string-formatted date of when the declaration was made.
      modifier:  the name of the user that later modified the declaration.
      modified:  a date of when the declaration was modified.

    Typically this information is initialized from a file; however, the 
    methods for adding and removing data for flavors can be used to create
    a new declared version of a product.  After all changes are made, the 
    write() method must be called to persist the information back to disk.

    This class understands a few rules for handling paths stored in 
    productDir, table_file, and ups_dir:
      *  A value of "none" indicates that the path explicitly does not have
           a logical value.  For example, for table_file, the product does not
           have a table file to set up the product.  For productDir, the 
           product is not formally installed anywhere.
      *  A value of None indicates that the path can be reset to a normalized
           default when written out.
      *  Any path can be absolutely specified (though they may get normalized
           when written out).
      *  If productDir is relative, it is assumed to be relative to the base
           directory of the software stack (not known to this class).
      *  If the ups_dir is relative, it is assumed to be relative to the 
           product installation directory, productDir.
      *  If the table file is relative, it is assumed to be relative to the
           ups_dir directory.  If the ups_dir is "none" or None, then the 
           table file is relative to productDir.
           

    @author  Raymond Plante
    """

    # Per-flavor metadata fields in file, in order of appearance.  
    # Values are stored in self.info
    _fields = [      
      "DECLARER",
      "DECLARED",
      "MODIFIER",
      "MODIFIED",
      "PROD_DIR",
      "UPS_DIR",
      "TABLE_FILE"
    ]

    def __init__(self, file, productName=None, version=None, verbosity=0, 
                 readFile=True):
        """
        create the version file data container.  If this file exists
        (and readFile is true), the data will be filled from its contents.
        @param file          the path to the file on disk.  
        @param productName   the name of the product.  If None, this will 
                                be set when the file is read.
        @param version       the version name.  If None, this will 
                                be set when the file is read.
        @param verbosity     the level of messages to spew on parsing.  If
                                < 0, parsing with be quiet; if > 0 extra 
                                messages (may) be printed
        @param readFile      if True, the file (if it exists) will be read 
                                in and its contents loaded into this instance.
        """

        # the file on disk where the declaration data is recorded.  This file
        # may not exist yet.
        self.file = file

        # the name of the registered product.  If None, the name is not known 
        # yet.
        self.name = productName

        # the product version.  If None, the name is not known yet.
        self.version = version

        # the attributes for this product for each flavor of this 
        # product-version.  Each key is a flavor and its value is 
        # dictionary of named properties.  Property names include:
        #   ups_dir:  the default directory containing the table file.
        #   table_file:  the full path to the table file
        #   productDir:  the installation directory
        #   declarer:  the name of the user that declared the product
        #   declared:  a string-formatted date of when the declaration was made.
        #   modifier:  the name of the user that later modified the declaration.
        #   modified:  a date of when the declaration was modified.
        self.info = {}

        if readFile and os.path.exists(self.file):
            self._read(self.file, verbosity)

    def makeProduct(self, flavor, eupsPathDir=None, dbpath=None):
        """
        create a Product instance for the given flavor.  If the product has 
        not be declared for the flavor, a  ProductNotFound exception is raised.

        @param flavor      : the desired flavor for the Product.  
        @param eupsPathDir : the product stack path to assume that product is 
                             installed under.  If the product install directory
                             is a relative path (product.dir), this eupsPathDir 
                             will be prepended in the output.  If None, no 
                             alterations of the product install directory will 
                             be done.
        @param dbpath      : the product database directory to store into 
                             the output product.db attribute.  If None, it will 
                             default to eupsPathDir/ups_db; if eupsPathDir is 
                             None, the product.db field will not be set.
        @return Product : a Product instance representing the product data
        """
        if not self.info.has_key(flavor):
            raise ProductNotFound(self.name, self.version, flavor)

        info = self.info[flavor]
        install = table = None
        if info.has_key("productDir"):
            install = info["productDir"]
            if eupsPathDir:
                # no need to check if install isabs()
                install = os.path.join(eupsPathDir, install)

        if info.has_key("table_file"):
            table = info["table_file"]

        if isRealFilename(table):
            if info.has_key("ups_dir"):
                # substitute out $UPS_DIR
                table = var_ups_dir_re.sub(info["ups_dir"], table)

            if not os.path.isabs(table) and not table.startswith("$PROD_DIR") \
               and info.has_key("ups_dir") and isRealFilename(info["ups_dir"]):
                table = os.path.join(info["ups_dir"], table)
            if not os.path.isabs(table) and not table.startswith("$PROD_DIR") \
               and install is not None and isRealFilename(install):
                table = os.path.join(install, table)

            if install:
                # substitute out $PROD_DIR
                table = var_prod_dir_re.sub(install, table)

        if eupsPathDir and not dbpath:
            dbpath = os.path.join(eupsPathDir, "ups_db")

        return Product(self.name, self.version, flavor, install, table, 
                       db=dbpath)
        

    def makeProducts(self):
        """
        return Product instances for all of the flavors declared in the file.
        @return Product[] :
        """
        return map(lambda x: self.makeProduct(x), self.info.keys())
          

    def getFlavors(self):
        """
        return the list of flavors declared in this file.
        @return string[] :
        """
        return self.info.keys()

    def hasFlavor(self, flavor):
        """
        return true if the product is declared for a given flavor 
        """
        return self.info.has_key(flavor)

    def addFlavor(self, flavor, installdir = None, tablefile = None, 
                  upsdir = None):
        """
        add a flavored version to this file.  If an entry for this flavor
        already exists, it will be modified.

        @param flavor :     the name of the platform flavor to be adding.
        @param installdir : the installation directory for the new version 
                              being added.  If None, this package as no 
                              install directory.
        @param tablefile :  the path to the table file for this version.  If 
                              this is relative, then it is assumed to be 
                              relative to the upsdir; if upsdir is None,
                              it is assumed to be relative to installdir
                              If None, the product has no tablefile.
        @param upsdir :     the path to the ups directory for this product.  
                              If None, a value of  "ups" will be assumed.  
        """
        if self.info.has_key(flavor):
            # if this flavor already exists, use it to set defaults.
            info = self.info[flavor]
            if not installdir and info.has_key("productDir"):
                installdir = info["productDir"]
            if not upsdir and info.has_key("ups_dir"):
                upsdir = info["ups_dir"]
            if not tablefile and info.has_key("table_file"):
                tablefile = info["table_file"]
          
        info = {}
        if installdir:
            installdir = installdir.rstrip('/')
            info["productDir"] = installdir

        if tablefile:
            # regularize upsdir: strip off leading installdir, upsdir
            if installdir and isRealFilename(installdir) and \
               os.path.isabs(tablefile) and \
               tablefile.startswith(installdir+'/'):

                # stripping off installdir
                tablefile = tablefile[len(installdir)+1:]

                # look for a ups directory
                if upsdir != "none":
                    upsdir = os.path.dirname(tablefile)
                    if upsdir:
                        tablefile = os.path.basename(tablefile)
                    else:
                        upsdir = "none"

            info["table_file"] = tablefile 

        if upsdir:
            # regularize upsdir: strip off leading installdir
            upsdir = upsdir.rstrip('/')
            if installdir and isRealFilename(upsdir) and \
               os.path.isabs(upsdir) and upsdir.startswith(installdir+'/'):
                upsdir = upsdir[len(installdir)+1:]
        if upsdir is None:
            upsdir = "none"
        info["ups_dir"] = upsdir

        if self.info.has_key(flavor):
            if self.info[flavor].has_key("declarer"):
                info["declarer"] = self.info[flavor]["declarer"]
            if self.info[flavor].has_key("declared"):
                info["declared"] = self.info[flavor]["declared"]

        if info.has_key("declarer") or info.has_key("declared"):
            # we're modifying
            info["modifier"] = who
            info["modified"] = ctimeTZ()
        else:
            # we're declaring
            info["declarer"] = who
            info["declared"] = ctimeTZ()

        # now save the info
        self.info[flavor] = info

    def removeFlavor(self, flavors):
        """
        remove versions for the given flavors.  

        @param flavors : a list of flavors to remove version information 
                            for.  If None, all available flavors will be 
                            removed.
        @return bool : False if product is not declared for the given flavors
        """
        if flavors is None:
            return self.removeFlavor(self.getFlavors())

        if not isinstance(flavors, list):
            flavors = [flavors]

        updated = False
        for flavor in flavors:
            if self.info.has_key(flavor):
                del self.info[flavor]
                updated = True

        return updated

    def isEmpty(self):
        """
        return true if there are no flavors of this product registered
        @return bool :
        """
        return (len(self.info.keys()) == 0)

    def _read(self, file=None, verbosity=0):
        """
        load data from a file

        @param file : the file to read the data from.   
        """
        if not file:
            file = self.file
        fd = open(file)

        flavor = None
        lineNo = 0                # line number in input file, for diagnostics
        for line in fd.readlines():
            lineNo += 1
            line = line.strip()
            line = re.sub(r"#.*$", "", line)
            if not line:
                continue

            #
            # Ignore Group: and End:, but check for needed fields.
            #
            # N.b. End is sometimes omitted, so a Group opens a new group
            #
            if re.search(r"^(End|Group)\s*:", line):
                if flavor:
                    if not self.info[flavor].has_key("productDir"):
                      if verbosity >= 0:
                        print >> sys.stderr, "Warning: Version file has no PROD_DIR for product %s %s %s\n  file=%s" % \
                            (self.name, self.version, flavor, file)

                      self.info[flavor]["productDir"] = None

                    if not self.info[flavor].has_key("table_file"):
                      if verbosity >= 0:
                        print >> sys.stderr, "Warning: Version file has no TABLE_FILE for product %s %s %s\n  file=%s" % \
                            (self.name, self.version, flavor, file)

                      self.info[flavor]["table_file"] = "none"

                    tablefile = self.info[flavor]["table_file"]
                    if not self.info[flavor].has_key("ups_dir") and \
                       isRealFilename(tablefile):
                        if verbosity >= 0 and \
                           tablefile != ("%s.table" % self.name) and \
                           not os.path.isabs(tablefile):
                            print >> sys.stderr, "Warning: Version file has no UPS_DIR for product %s %s %s with TABLE_FILE=%s\n  file=%s" % \
                            (self.name, self.version, flavor, tablefile, file)

                        self.info[flavor]["ups_dir"] = "none"

                continue
            #
            # Get key = value
            #
            mat = re.search(r"^(\w+)\s*=\s*(.*)", line, re.IGNORECASE)
            if mat:
                key = mat.group(1).lower()
                if key == "prod_dir":
                    key = "productDir"

                value = re.sub(r"^\"|\"$", "", mat.group(2))
            else:
                raise RuntimeError, \
                      ("Unexpected line \"%s\" at %s:%d" % (line, self.file, lineNo))
            #
            # Check for information about product
            #
            if key == "file":
                if value.lower() != "version":
                    raise RuntimeError, \
                          ('Expected "File = Version"; saw "%s" at %s:%d' % (line, self.file, lineNo))

            elif key == "product":
                if not self.name:
                    self.name = value
                elif self.name != value:
                  if verbosity >= 0:
                    print >> sys.stderr, \
                        "Warning: Unexpected product name, %s, in version file; expected %s,\n  file=%s" % \
                        (value, self.name, file)

            elif key == "version":
                if not self.version:
                    self.version = value
                elif self.version != value:
                  if verbosity >= 0:
                    print >> sys.stderr, \
                        "Warning: Unexpected version name, %s, for %s in version file; expected %s,\n  file=%s" % \
                        (value, self.name, self.version, file)

            elif key == "flavor": # Now look for flavor-specific blocks
                flavor = value
                if not self.info.has_key(flavor):
                    self.info[flavor] = {}

            else:
                value = re.sub(r"^\"(.*)\"$", r"\1", mat.group(2)) # strip ""

                if key == "qualifiers":
                    if value:           # flavor becomes e.g. Linux:build
                        newflavor = "%s:%s" % (flavor, value)
                        self.info[newflavor] = self.info[flavor]
                        del self.info[flavor]
                        flavor = newflavor
                else:
                    self.info[flavor][key] = value

        fd.close()
        

    def write(self, trimDir=None, file=None):
        """
        write the data out to a file.  If this version file contains no
        declared flavors, this function will remove the file, if it exists.

        @param trimDir  strip off this leading directory name from all
                          paths written out.
        @param file : the file to write the version data out to.  If None,
                        write to the configured location.
        """
        if not file:
            file = self.file
        if self.isEmpty():
            if os.path.exists(file):  os.remove(file)
            return

        fd = open(file, "w")

        print >> fd, """FILE = version
PRODUCT = %s
VERSION = %s
#***************************************\
""" % (self.name, self.version)

        for fq in self.info.keys():
            mat = re.search(r"^([^:]+)(:?:(.*)$)?", fq)
            flavor = mat.group(1)
            qualifier = mat.group(3)
            if not qualifier:
                qualifier = ""

            print >> fd, """
Group:
   FLAVOR = %s
   QUALIFIERS = "%s"\
""" % (flavor, qualifier)
        
            #
            # Strip trimDir from directory names
            #
            info = self.info[fq].copy()
            for k in info.keys():
                value = info[k]
                
                if re.search(r"^%s/" % trimDir, value):
                    if os.path.isfile(value) or os.path.isdir(value):
                        if os.path.commonprefix([trimDir, value]) == trimDir:
                            info[k] = re.sub(r"^%s/" % trimDir, "", value)
                            utils.debug("Stripping eupsPathDir", self.info[fq][k])
                            if k == "table_file":
                                info[k] = \
                                    re.sub(r"^ups_db/", "", self.info[fq][k])
                                info["ups_dir"] = "$UPS_DIR";

            for field in self._fields:
                if field == "PROD_DIR":
                    k = "productDir"
                else:
                    k = field.lower()

                if info.has_key(k):
                    value = info[k]
                            
                    if not value:
                        if k == "productDir":
                            value = "none"
                        elif k == "table_file":
                            #debug("Setting table_file")
                            value = "none"
                        else:
                            continue

                    print >> fd, "   %s = %s" % (field.upper(), value)

        print >> fd, "End:"

        fd.close()



