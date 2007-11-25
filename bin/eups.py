#!/usr/bin/env python

# Routines that talk to eups; all currently use popen on eups shell commands,
# but you're not supposed to know that

import os
import re
import sys

if not os.environ.has_key('SHELL'):
    os.environ['SHELL'] = '/bin/sh'

def current(product="", dbz="", flavor = ""):
    """Return the current version of a product; if product is omitted,
    return a list of (product, version) for all products"""

    return _current_or_setup("current", product, dbz, flavor)

def setup(product="", dbz="", flavor = ""):
    """Return the setup version of a product; if product is omitted,
    return a list of (product, version) for all products"""

    return _current_or_setup("setup", product, dbz, flavor)

def _current_or_setup(characteristic, product="", dbz="", flavor = ""):
    """Return the \"characteristic\" (e.g. current) version of a product; if product is omitted,
    return a list of (product, version) for all products"""

    opts = ""
    if dbz:
        opts += " --select-db %s" % (dbz)
    if flavor:
        opts += " --flavor %s" % (flavor)

    products = []
    for line in os.popen("eups list --%s %s %s 2>&1" % (characteristic, opts, product)).readlines():
        if re.search(r"^ERROR", line):
            raise RuntimeError, line
        elif re.search(r"^WARNING", line):
            continue

        if re.search(r"^No version is declared current", line) and product:
            return None
            
        match = re.findall(r"\S+", line)
        if product:
            return match[0]

        products += [match[0:2]]

    return products

def declare(flavor, dbz, tablefile, products_root, product_dir, product, version, declare_current = False,
            noaction = False):
    """Declare a product.  product_dir may be None to just declare the product current (or
    use declareCurrent)"""

    opts = ""
    if declare_current:
        opts += " -c"
    if dbz:
        opts += " -z %s" % dbz

    if product_dir:
        opts += " --root %s" % os.path.join(products_root, product_dir)

        tableopt = "-m"
        if tablefile != "none":
            if ("%s.table" % (product)) != tablefile:
                tableopt = "-M"
        opts += " %s %s" % (tableopt, tablefile)

    try:
        cmd = "eups_declare --flavor %s%s %s %s" % \
              (flavor, opts, product, version)
        if noaction:
            print cmd
        else:
            if os.system(cmd) != 0:
                raise RuntimeError, cmd
    except KeyboardInterrupt:
        raise
    except:
        print >> sys.stderr, "Failed to declare product %s (version %s, flavor %s)" % \
              (product, version, flavor)

def declareCurrent(flavor, dbz, product, version, noaction = False):
    """Declare a product current"""

    declare(flavor, dbz, None, None, None, product, version, declare_current=True,
            noaction=noaction)

def dependencies(product, version, dbz="", flavor=""):
    """Return a product's dependencies in the form of a list of tuples
    (product, version, flavor)
"""

    opts = ""
    if dbz:
        opts += " --select-db %s" % (dbz)
    if flavor:
        opts += " --flavor %s" % (flavor)

    productList = os.popen("eups_setup setup %s -n --verbose %s %s 2>&1 1> /dev/null" % \
                    (opts, product, version)).readlines()

    dep_products = {}
    deps = []
    for line in productList:
        if re.search("^FATAL ERROR:", line):
            raise RuntimeError, ("Fatal error setting up %s:" % (product), "\t".join(["\n"] + productList))

        mat = re.search(r"^Setting up:\s+(\S+)\s+Flavor:\s+(\S+)\s+Version:\s+(\S+)", line)
        if not mat:
            continue
        
        (oneProduct, oneFlavor, oneVersion) = mat.groups()
        oneDep = (oneProduct, oneVersion, oneFlavor) # note the change in order

        # prune repeats of identical product version/flavor
        versionHash = "%s:%s" % (oneVersion, oneFlavor)
        if dep_products.has_key(oneProduct) and dep_products[oneProduct] == versionHash:
            continue
        dep_products[oneProduct] = versionHash

        deps += [oneDep]

    return deps

def dependencies_from_table(tableFile):
    """Return a list of tuples (product, version) that need to be
    setup, given a table file.

    N.b. Note that conditionals aren't handled properly
    N.b. This is the top-level requirements, it isn't computed recursively"""

    try:
        fd = open(tableFile)
    except IOError:
        return None

    products = []
    for line in fd:
        mat = re.search(r"^\s*(setupRequired|setupOptional)\s*\(\s*([^)]+)\s*\)", line)
        if mat:
            args = []
            ignore = False;             # ignore next argument
            for a in re.sub(r'^"|"$', "", mat.group(2)).split():
                if a == "-f" or a == "--flavor": # ignore flavor specifications
                    ignore = True
                    continue
                    
                if ignore:
                    ignore = False
                else:
                    args += [a]
            
            print args

            if len(args) == 1:
                args += [None]
            elif len(args) == 2:
                pass
            else:
                print >> sys.stderr, "Failed to parse: ", line,
                args = args[0:2]

            products += [tuple(args)]

    return products

def flavor():
    """Return the current flavor"""
    
    if os.environ.has_key("EUPS_FLAVOR"):
        return os.environ["EUPS_FLAVOR"]
    return str.split(os.popen('eups_flavor').readline(), "\n")[0]

def list(product, version = "", dbz = "", flavor = "", quiet=False):
    """Return a list of declared versions of a product; if the
    version is specified, just return the properties of that version.
    The version may be "current" or "setup" to return the current
    or setup version.

    The return value for each product is a list of lists:
       [[version, database, directory, isCurrent, isSetup], ...]
    (if only one version matches, the return is a single list; if no versions
    match, you'll get None)
    """

    if version == "current":
        version = current(product)
    elif version == "setup":
        version = setup(product)

    opts = ""
    if dbz:
        opts += " --select-db %s" % (dbz)
    if flavor:
        opts += " --flavor %s" % (flavor)

    result = []
    for info in os.popen("eups list %s --quiet --verbose %s %s" % (opts, product, version)).readlines():
        oneResult = re.findall(r"\S+", info)

        if len(oneResult) == 3:
            oneResult += [False]
        else:
            if oneResult[3] == "Current":
                oneResult[3] = True
            else:
                oneResult[3:3] = [False]

        if len(oneResult) == 4:
            oneResult += [False]
        else:
            assert (oneResult[4] == "Setup")
            oneResult[4] = True
        assert len(oneResult) == 5

        result += [oneResult]

        if version:
            return oneResult
        
    if len(result):
        return result
    else:
        None

def database(product, version="current", dbz = "", flavor = ""):
    """Return the database for the specified product and version"""

    vals = list(product, version, dbz, flavor)
    if vals:
        return vals[1]
    else:
        None        

def directory(product, version="current", dbz = "", flavor = ""):
    """Return the PRODUCT_DIR for the specified product and version"""

    vals = list(product, version, dbz, flavor)
    if vals:
        return vals[2]
    else:
        None

productDir = directory                  # provide an alias

def isCurrent(product, version, dbz = "", flavor = ""):
    """Return True iff the the specified product and version is current"""

    vals = list(product, version, dbz, flavor)
    if vals:
        return vals[3]
    else:
        False       

def isSetup(product, version, dbz = "", flavor = ""):
    """Return True iff the the specified product and version is setup"""

    vals = list(product, version, dbz, flavor)
    if vals:
        return vals[4]
    else:
        False

def table(product, version, flavor = ""):
    """Return the full path of a product's tablefile"""
    if flavor:
        flavor = "--flavor %s" % (flavor)
        
    info = os.popen("eups list %s --table %s %s" % \
                    (flavor, product, version)).readlines()[0].split("\n")
    for i in info:
        if re.search("^WARNING", i):
            print >> sys.stderr, i
        else:
            return re.findall(r"\S+", i)[0]

    return None

#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-

def version(versionString='$Name: not supported by cvs2svn $'):
    """Set a version ID from env, or
    a cvs or svn ID string (dollar name dollar or dollar HeadURL dollar)"""

    if re.search(r"^[$]Name:\s+", versionString):
        # CVS.  Extract the tagname
        version = re.search(r"^[$]Name:\s+([^ $]*)", versionString).group(1)
        if version == "":
            version = "cvs"
    elif re.search(r"^[$]HeadURL:\s+", versionString):
        # SVN.  Guess the tagname from whatever follows "tags" (or "TAGS") in the URL
        version = "svn"                 # default
        parts = versionString.split("/")
        for i in range(0, len(parts) - 1):
            if parts[i] == "tags" or parts[i] == "TAGS":
                version = parts[i + 1]
    else:
        version = "unknown"

    return version


#-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-=-

# Like getopt.getopt, but supports a dictionary options of recognised
# options, supports long option names, allows aliases, allows options
# to follow arguments, and sets the values of flag options to the
# number of occurrences of the flag

class Getopt:
    def __init__(self, options, argv = sys.argv, aliases = dict(), msg = None):
        """A class to represent the processed command line arguments.

options is a dictionary whose keys are is the short name of the option
(and the one that it'll be indexed as), and the value is a tuple; the
first element is a boolean specifying if the option takes a value; the
second (if not None) is a long alias for the option, and the third is
a help string.  E.g.
    ["-i", (False, "--install", "Extract and install the specified package")],

aliases is another dictionary, with values that specify additional long versions
of options; e.g.
    ["-i", ["--extract"]],

Options may be accessed as Getopt.options[], and non-option arguments as Getopt.argv[]

msg is the help message associated with the command
        
"""
        if msg:
            self.msg = msg
        else:
            self.msg = "Command [options] arguments"
        #
        # Provide a -h/--help option if -h is omitted
        #
        if not options.has_key('-h'):
            options["-h"] = (False, "--help", "Print this help message")        
        #
        # Build the options string for getopt() and a hash of the long options
        #
        optstr = ""
        longopts = {}
        for opt in options.keys():
            optstr += opt[1]
            if options[opt][0]:
                optstr += ":"

            if options[opt][1]:
                longopts[options[opt][1]] = opt

        for opt in aliases.keys():
            longopts[aliases[opt][0]] = opt
        #
        # Massage the arguments
        #
        nargv = []
        opts = {}
        verbose = 0
        i = 0
        while i < len(argv) - 1:
            i = i + 1
            a = argv[i]

            if re.search(r"^[^-]", a):
                nargv += [a]
                continue

            mat = re.search(r"^([^=]+)=(.*)$", a)
            if mat:
                (a, val) = mat.groups()
            else:
                val = None            

            if longopts.has_key(a):
                a = longopts[a]

            if options.has_key(a):
                if options[a][0]:
                    if val:
                        opts[a] = val
                    else:
                        try:
                            opts[a] = argv[i + 1]; i += 1
                        except IndexError:
                            raise RuntimeError, ("Option %s expects a value" % a)
                else:
                    if opts.has_key(a):
                        opts[a] += 1
                    else:
                        opts[a] = 1
            else:
                raise RuntimeError, ("Unrecognised option %s" % a)
        #
        # Save state
        #
        self.cmd_options = options  # possible options
        self.cmd_aliases = aliases  # possible aliases
        self.options = opts         # the options provided
        self.argv = nargv           # the surviving arguments

    def has_option(self, opt):
        """Whas the option "opt" provided"""
        return self.options.has_key(opt)

    def usage(self):
        """Print a usage message based on the options list"""

        print >> sys.stderr, """\
Usage:
    %s
Options:""" % self.msg

        def asort(a,b):
            """Sort alphabetically, so -C, --cvs, and -c appear together"""

            a = re.sub(r"^-*", "", a)       # strip leading -
            b = re.sub(r"^-*", "", b)       # strip leading -

            if a.upper() != b.upper():
                a = a.upper(); b = b.upper()

            if a < b:
                return -1
            elif a == b:
                return 0
            else:
                return 1

        for opt in sorted(self.cmd_options.keys(), cmp = asort):
            optstr = "%2s%1s %s" % \
                     (opt,
                      (not self.cmd_options[opt][1] and [""] or [","])[0],
                      self.cmd_options[opt][1] or "")
            optstr = "%-16s %s" % \
                     (optstr, (not self.cmd_options[opt][0] and [""] or ["arg"])[0])
            
            print >> sys.stderr, "   %-21s %s" % \
                  (optstr, ("\n%25s"%"").join(self.cmd_options[opt][2].split("\n")))
            if self.cmd_aliases.has_key(opt):
                print >> sys.stderr, "                         Alias%s:" % \
                      (len(self.cmd_aliases[opt]) == 1 and [""] or ["es"])[0], " ".join(self.cmd_aliases[opt])
#
# Expand a build file
#
def expandBuildFile(ofd, ifd, product, version, svnroot=None, cvsroot=None):
    """Expand a build file, reading from ifd and writing to ofd"""
    #
    # A couple of functions to set/guess the values that we'll be substituting
    # into the build file
    #
    # Guess the value of CVSROOT
    #
    def guess_cvsroot(cvsroot):
        if cvsroot:
            pass
        elif os.environ.has_key("CVSROOT"):
            cvsroot = os.environ["CVSROOT"]
        elif os.path.isdir("CVS"):
            try:
                rfd = open("CVS/Root")
                cvsroot = re.sub(r"\n$", "", rfd.readline())
                del rfd
            except IOError, e:
                print >> sys.stderr, "Tried to read \"CVS/Root\" but failed: %s" % e

        return cvsroot    
    #
    # Guess the value of SVNROOT
    #
    def guess_svnroot(svnroot):
        if svnroot:
            pass
        elif os.path.isdir(".svn"):
            try:
                rfd = os.popen("svn info .svn")
                for line in rfd:
                    mat = re.search(r"^Repository Root: (\S+)", line)
                    if mat:
                        svnroot = mat.group(1)
                        break
                del rfd
            except IOError, e:
                print >> sys.stderr, "Tried to read \"CVS/Root\" but failed: %s" % e

        return svnroot
    #
    # Here's the function to do the substitutions
    #
    subs = {}                               # dictionary of substitutions
    subs["CVSROOT"] = guess_cvsroot(cvsroot)
    subs["SVNROOT"] = guess_svnroot(svnroot)
    subs["PRODUCT"] = product
    subs["VERSION"] = version

    def subVar(name):
        var = name.group(1).upper()
        if subs.has_key(var):
            return subs[var]
        return "XXX"
    #
    # Actually do the work
    #
    for line in ifd:
        # Attempt substitutions
        line = re.sub(r"@([^@]+)@", subVar, line)

        print >> ofd, line,
