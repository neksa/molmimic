import os
import shutil
import tempfile

try:
    from toil.lib.docker import apiDockerCall
except ImportError:
    apiDockerCall = None
    import subprocess
    maxcluster_path = os.path.dirname(os.path.dirname(subprocess.check_output(["which", "maxcluster"])))

def run_maxcluster(*args, **kwds):
    work_dir = kwds.pop("work_dir", None)
    docker = kwds.pop("docker", True)
    job = kwds.pop("job", None)

    if work_dir is None:
        work_dir = os.getcwd()

    if "file_list" in kwds and not "l" in kwds:
        kwds["l"] = kwds.pop("file_list")
    else:
        kwds.pop("file_list", None)

    log = kwds.get("log", False)
    if log and not isinstance(log, str):
        f = tempfile.NamedTemporaryFile(dir=work_dir, suffix=".log", delete=False)
        f.close()
        kwds["log"] = f.name

    file_kwds = ["log", "e", "p", "l", "R", "Rl", "Ru", "F", "M"]
    in_file_kwds = ["e", "p", "l", "F", "M"]
    parameters = ["-"+a for a in args]
    for k, v in kwds.iteritems():
        if k not in file_kwds:
            parameters += ["-{}".format(k), str(v)]
    job.log("ORIG PARAMS: {}".format(parameters))
    file_parameters = {k:v for k, v in kwds.iteritems() if k in file_kwds}

    if docker and apiDockerCall is not None and job is not None:
        for k,f in file_parameters.iteritems():
            if k in in_file_kwds and not os.path.abspath(os.path.dirname(f)) == os.path.abspath(work_dir):
                shutil.copy(f, work_dir)
            job.log("BASENAMING: {}".format(os.path.basename(f)))
            parameters += ["-{}".format(k), os.path.basename(f)]

        oldcwd = os.getcwd()
        os.chdir(work_dir)
        try:
            out = apiDockerCall(job,
                          'edraizen/maxcluster:latest',
                          working_dir="/data",
                          volumes={work_dir:{"bind":"/data", "mode":"rw"}},
                          parameters=parameters
                          )
        except (SystemExit, KeyboardInterrupt):
            raise
        except:
            job.log("FILE LIST IS [{}]".format(open(file_parameters["l"]).read()))
            raise
            #return run_scwrl(pdb_file, output_prefix=output_prefix, framefilename=framefilename,
            #    sequencefilename=sequencefilename, paramfilename=paramfilename, in_cystal=in_cystal,
            #    remove_hydrogens=remove_hydrogens, remove_h_n_term=remove_h_n_term, work_dir=work_dir, docker=False)
        os.chdir(oldcwd)
    else:
        file_args = []
        for k,f in file_parameters.iteritems():
            parameters += ["-{}".format(k), f]
        args = [maxcluster_path]+file_args+parameters
        try:
            out = subprocess.check_output(args)
        except (SystemExit, KeyboardInterrupt):
            raise
        except Exception as e:
            raise
            #raise RuntimeError("APBS failed becuase it was not found in path: {}".format(e))

    if "log" in kwds and os.path.isfile(kwds["log"]):
        return kwds["log"]
    return out

def get_centroid(log_file, work_dir=None, docker=True, job=None):
    parse_centroids = False
    best_centroid_size = None
    best_centroid_file = None

    with open(log_file) as log:
        for line in log:
            job.log("LINE: {}".format(line.rstrip()))
            if not parse_centroids and line.startswith("INFO  : Centroids"):
                parse_centroids = True
                next(log)
                next(log)
            elif parse_centroids and line.startswith("INFO  : ="):
                break
            elif parse_centroids:
                job.log("PARSING LINE: {}".format(line.rstrip()))
                fields = line.rstrip().split()
                size, pdb_file = fields[-3], fields[-1]
                if best_centroid_size is None or int(size)>best_centroid_size:
                    best_centroid_size = int(size)
                    best_centroid_file = pdb_file

    return best_centroid_file

def get_hierarchical_tree(log_file):
    import networkx as nx
    nx_tree = nx.DiGraph()
    parse_tree = False

    with open(log_file) as log:
        for line in log:
            job.log("LINE: {}".format(line.rstrip()))
            if not parse_tree and line.startswith("INFO  : Hierarchical Tree"):
                parse_tree = True
                next(log)
                next(log)
            elif parse_tree and line.startswith("INFO  : ="):
                break
            elif parse_tree:
                _, node, info = line.rstrip().split(":")
                node = int(node.strip())
                nx_tree.add_node(node)

                fields = [f.strip() for f in info.split()]
                item2, item2 = map(int, fields[:2])
                distance = float(fields[2])

                if item1>0 and item2>0:
                    pdb1, pdb2 = fields[3:5]
                    nx_tree.add_node(item1, pdb=pdb1)
                    nx_tree.add_node(item2, pdb=pdb2)
                elif item1>0 and item2<0:
                    #Node 2 already in graph
                    pdb1 = fields[3]
                    nx_tree.add_node(item1, pdb=pdb1)
                elif item1<0 and item2>0:
                    #Node 1 already in graph
                    pdb2 = fields[3]
                    nx_tree.add_node(item2, pdb=pdb2)

                nx_tree.add_edge(node, item1)
                nx_tree.add_edge(node, item2)
