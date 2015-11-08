from pbcore.io import FastaIO
from pbcommand.engine import run_cmd as pb_run_cmd
from contextlib import contextmanager
from falcon_kit import run_support as support
from falcon_kit.mains import run as support2
import glob
import hashlib
import itertools
import json
import logging
import os
import re
import StringIO
import sys

log = logging.getLogger(__name__)


@contextmanager
def cd(newdir):
    prevdir = os.getcwd()
    say('CD: %r <- %r' %(newdir, prevdir))
    os.chdir(os.path.expanduser(newdir))
    try:
        yield
    finally:
        say('CD: %r -> %r' %(newdir, prevdir))
        os.chdir(prevdir)

def say(msg):
        log.info(msg)
        print(msg)

def run_cmd(cmd, *args, **kwds):
    say('RUN: %s' %repr(cmd))
    rc = pb_run_cmd(cmd, *args, **kwds)
    say(' RC: %s' %repr(rc))
    if rc.exit_code:
        raise Exception(repr(rc))

def _get_config(fn):
    """Return a dict.
    """
    return support.get_config(support.parse_config(fn))

def _get_config_from_json_fileobj(ifs_json):
    i_json = ifs_json.read()
    say('JSON=\n%s' %i_json[:1024]) # truncated
    return json.loads(i_json)

def run_falcon_config_get_fasta(input_files, output_files):
        i_config_fn, = input_files
        o_fofn_fn, = output_files
        config = _get_config(i_config_fn)
        i_fofn_fn = config['input_fofn_fn']
        msg = '%r -> %r' %(i_fofn_fn, o_fofn_fn)
        say(msg)
        with cd(os.path.dirname(i_fofn_fn)):
            return support.make_fofn_abs(i_fofn_fn, o_fofn_fn)

def run_falcon_config(input_files, output_files):
        i_config_fn, i_fasta_fofn = input_files
        o_json_fn, = output_files
        config = _get_config(i_config_fn)
        config['input_fofn_fn'] = os.path.abspath(i_fasta_fofn)
        config['ORIGINAL_SELF'] = i_config_fn
        output = json.dumps(config)
        out = StringIO.StringIO()
        out.write(output)
        log.info('falcon_config:\n' + output)
        with open(o_json_fn, 'w') as ofs:
            ofs.write(output)
        #return run_cmd('echo hi', open(hello, 'w'), sys.stderr, shell=False)

def run_falcon_make_fofn_abs(input_files, output_files):
        i_json_fn, = input_files
        o_fofn_fn, = output_files
        config = _get_config_from_json_fileobj(open(i_json_fn))
        i_fofn_fn = config['input_fofn_fn']
        if not i_fofn_fn.startswith('/'):
            # i_fofn_fn can be relative to the location of the config file.
            original_config_fn = config['ORIGINAL_SELF']
            i_fofn_fn = os.path.join(os.path.dirname(original_config_fn), i_fofn_fn)
        msg = 'run_falcon_make_fofn_abs(%r -> %r)' %(i_fofn_fn, o_fofn_fn)
        say(msg)
        with cd(os.path.dirname(i_fofn_fn)):
            return support.make_fofn_abs(i_fofn_fn, o_fofn_fn)

def read_fns(fofn):
    print('read from fofn:%s' %repr(fofn))
    with open(fofn) as ifs:
        return ifs.read().split()
def write_fns(fofn, fns):
    """Remember the trailing newline, for fasta2DB.
    """
    print('write to fofn:%s' %repr(fofn))
    with open(fofn, 'w') as ofs:
        return ofs.write('\n'.join(list(fns) + ['']))

def run_falcon_build_rdb(input_files, output_files):
    print('output_files: %s' %(repr(output_files)))
    cwd = os.getcwd()
    odir = os.path.realpath(os.path.abspath(os.path.dirname(output_files[0])))
    if True: #debug
        if cwd != odir:
            raise Exception('%r != %r' %(cwd, odir))
    # TODO: Take adv of existing raw_reads.db. (This TODO was copied from FALCON.)
    i_json_config_fn, i_fofn_fn = input_files
    print('output_files: %s' %repr(output_files))
    run_daligner_jobs_fn, job_done_fn = output_files
    #o_fofn_fn, = output_files
    config = _get_config_from_json_fileobj(open(i_json_config_fn))
    script_fn = os.path.join(odir, 'prepare_rdb.sh')
    #job_done_fn = os.path.join(odir, 'job.done') # not needed in pbsmrtpipe today tho
    #run_daligner_jobs_fn = os.path.join(odir, 'run_daligner_jobs.sh')
    #write_fns(o_fofn_fn, [script_fn])
    #run_cmd('touch %s' %dummy_fn, sys.stdout, sys.stderr, shell=False)
    support.build_rdb(i_fofn_fn, cwd, config, job_done_fn, script_fn, run_daligner_jobs_fn)
    run_cmd('bash %s' %script_fn, sys.stdout, sys.stderr, shell=False)

def touch(fn):
    run_cmd('touch %s' %fn, sys.stdout, sys.stderr, shell=False)

def run_daligner_jobs(input_files, output_files, db_prefix='raw_reads'):
    print('run_daligner_jobs: %s %s' %(repr(input_files), repr(output_files)))
    i_json_config_fn, run_daligner_job_fn, = input_files
    o_fofn_fn, = output_files
    db_dir = os.path.dirname(run_daligner_job_fn)
    cmds = ['pwd', 'ls -al']
    fns = ['.{pre}.bps', '.{pre}.idx', '{pre}.db']
    cmds += [r'\rm -f %s' %fn for fn in fns]
    cmds += ['ln -sf {dir}/%s .' %fn for fn in fns]
    cmd = ';'.join(cmds).format(
            dir=os.path.relpath(db_dir), pre=db_prefix)
    run_cmd(cmd, sys.stdout, sys.stderr, shell=True)
    cwd = os.getcwd()
    config = _get_config_from_json_fileobj(open(i_json_config_fn))
    tasks = create_daligner_tasks(
            run_daligner_job_fn, cwd, db_prefix, db_prefix+'.db', config)
    odirs = []
    for jobd, args in tasks.items():
        with cd(jobd):
            support.run_daligner(**args)
            script_fn = args['script_fn']
            run_cmd('bash %s' %script_fn, sys.stdout, sys.stderr, shell=False)
            odirs.append(os.path.dirname(script_fn))
    write_fns(o_fofn_fn, itertools.chain.from_iterable(glob.glob('%s/*.las' %d) for d in odirs))


def create_daligner_tasks(run_jobs_fn, wd, db_prefix, db_file, config, pread_aln = False):
    job_id = 0
    tasks = dict() # uid -> parameters-dict

    nblock = support2.get_nblock(db_file)

    # Not in other version. Still needed?
    for pid in xrange(1, nblock + 1):
        # support.run_daligner() links into this at end. Maybe we should change that.
        support.make_dirs("%s/m_%05d" % (wd, pid))

    re_daligner = re.compile(r'\bdaligner\b')

    line_count = 0
    job_descs = support2.get_daligner_job_descriptions(open(run_jobs_fn), db_prefix)
    for desc, bash in job_descs.iteritems():
        job_uid = '%08d' %line_count
        line_count += 1
        jobd = os.path.join(wd, "./job_%s" % job_uid)
        support.make_dirs(jobd)
        call = "cd %s; ln -sf ../.%s.bps .; ln -sf ../.%s.idx .; ln -sf ../%s.db ." % (jobd, db_prefix, db_prefix, db_prefix)
        rc = os.system(call)
        if rc:
            raise Exception("Failure in system call: %r -> %d" %(call, rc))
        job_done = os.path.abspath("%s/job_%s_done" %(jobd, job_uid))
        if pread_aln:
            bash = re_daligner.sub("daligner_p", bash)
        script_fn = os.path.join(jobd , "rj_%s.sh"% (job_uid))
        args = {
            'daligner_cmd': bash,
            'db_prefix': db_prefix,
            'nblock': nblock,
            'config': config,
            'job_done': job_done,
            'script_fn': script_fn,
        }
        daligner_task = args #make_daligner_task( task_run_daligner )
        tasks[jobd] = daligner_task
        job_id += 1
    return tasks

def run_merge_consensus_jobs(input_files, output_files, db_prefix='raw_reads'):
    print('run_merge_consensus_jobs: %s %s' %(repr(input_files), repr(output_files)))
    i_json_config_fn, run_daligner_job_fn, i_fofn_fn = input_files
    o_fofn_fn, = output_files
    db_dir = os.path.dirname(run_daligner_job_fn)
    cmds = ['pwd', 'ls -al']
    fns = ['.{pre}.bps', '.{pre}.idx', '{pre}.db']
    cmds += ['rm -f %s' %fn for fn in fns]
    cmds += ['ln -sf {dir}/%s .' %fn for fn in fns]
    cmd = ';'.join(cmds).format(
            dir=os.path.relpath(db_dir), pre=db_prefix)
    run_cmd(cmd, sys.stdout, sys.stderr, shell=True)
    cwd = os.getcwd()
    config = _get_config_from_json_fileobj(open(i_json_config_fn))
    # i_fofn_fn has the .las files, so create_merge_tasks does not need to look for theme.
    tasks = create_merge_tasks(i_fofn_fn, run_daligner_job_fn, cwd, db_prefix=db_prefix, config=config)
    for p_id, argstuple in tasks.items():
            merge_args, cons_args = argstuple
            job_done = os.path.join(cwd, "rp_%05d_done" %p_id)
            script_fn = os.path.join(cwd, "rp_%05d.sh" % (p_id))
            merge_args['job_done'] = job_done
            merge_args['script_fn'] = script_fn
            support.run_las_merge(**merge_args)
            run_cmd('bash %s' %script_fn, sys.stdout, sys.stderr, shell=False)
            job_done = os.path.join(cwd, 'preads', "c_%05d_done" %p_id)
            script_fn = os.path.join(cwd, 'preads', "c_%05d.sh" %(p_id))
            cons_args['job_done'] = job_done
            cons_args['script_fn'] = script_fn
            support.run_consensus(**cons_args)
            run_cmd('bash %s' %script_fn, sys.stdout, sys.stderr, shell=False)
    write_fns(o_fofn_fn, sorted(os.path.abspath(f) for f in glob.glob('preads/out*.fasta')))

def create_merge_tasks(i_fofn_fn, run_jobs_fn, wd, db_prefix, config):
    tasks = {} # pid -> (merge_params, cons_params)
    mjob_data = {}

    with open(run_jobs_fn) as f :
        for l in f:
            l = l.strip().split()
            if l[0] not in ( "LAsort", "LAmerge", "mv" ):
                continue
            if l[0] == "LAsort":
                # We now run this part w/ daligner, but we still need
                # a small script for some book-keeping.
                p_id = int( l[2].split(".")[1] )
                mjob_data.setdefault( p_id, [] )
                #mjob_data[p_id].append(  " ".join(l) ) # Already done w/ daligner!
            if l[0] == "LAmerge":
                l2 = l[2].split(".")
                if l2[1][0] == "L":
                    p_id = int(  l[2].split(".")[2] )
                    mjob_data.setdefault( p_id, [] )
                    mjob_data[p_id].append(  " ".join(l) )
                else:
                    p_id = int( l[2].split(".")[1] )
                    mjob_data.setdefault( p_id, [] )
                    mjob_data[p_id].append(  " ".join(l) )
            if l[0] == "mv":
                l2 = l[1].split(".")
                if l2[1][0] == "L":
                    p_id = int(  l[1].split(".")[2] )
                    mjob_data.setdefault( p_id, [] )
                    mjob_data[p_id].append(  " ".join(l) )
                else:
                    p_id = int( l[1].split(".")[1] )
                    mjob_data.setdefault( p_id, [] )
                    mjob_data[p_id].append(  " ".join(l) )

    # Could be L1.* or preads.*
    re_las = re.compile(r'\.(\d*)(\.\d*)?\.las$')

    for p_id in mjob_data:
        s_data = mjob_data[p_id]

        support.make_dirs("%s/preads" % (wd) )
        support.make_dirs("%s/las_files" % (wd) )
        merge_subdir = "m_%05d" %p_id
        merge_dir = os.path.join(wd, merge_subdir)
        support.make_dirs(merge_dir)
        with cd(merge_dir):
            print("i_fofn_fn=%r" %i_fofn_fn)
            # Since we could be in the gather-task-dir, instead of globbing,
            # we will read the fofn.
            for fn in open(i_fofn_fn).read().splitlines():
                basename = os.path.basename(fn)
                mo = re_las.search(basename)
                if not mo:
                    continue
                left_block = int(mo.group(1))
                if left_block != p_id:
                    # By convention, m_00005 merges L1.5.*.las, etc.
                    continue
                rel_fn = os.path.relpath(fn)
                print("symlink %r <- %r" %(rel_fn, os.path.basename(fn)))
                os.symlink(rel_fn, os.path.basename(fn))

        merge_script_file = os.path.abspath( "%s/m_%05d/m_%05d.sh" % (wd, p_id, p_id) )
        with open(merge_script_file, "w") as merge_script:
            print >> merge_script, 'DIR=$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )'
            print >> merge_script, 'set -vex'
            print >> merge_script, 'cd ${DIR}'
            #print >> merge_script, """for f in `find .. -wholename "*job*/%s.%d.%s.*.*.las"`; do ln -sf $f .; done""" % (db_prefix, p_id, db_prefix)
            for l in s_data:
                print >> merge_script, l
            print >> merge_script, "ln -sf ../m_%05d/%s.%d.las ../las_files" % (p_id, db_prefix, p_id) 
            print >> merge_script, "ln -sf ./m_%05d/%s.%d.las .. " % (p_id, db_prefix, p_id) 
            
        #job_done = makePypeLocalFile(os.path.abspath( "%s/m_%05d/m_%05d_done" % (wd, p_id, p_id)  ))
        parameters =  {"p_script_fn": merge_script_file, 
                       "config": config}
        merge_task = parameters

        out_file = os.path.abspath("%s/preads/out.%05d.fasta" %(wd, p_id))
        #out_done = makePypeLocalFile(os.path.abspath( "%s/preads/c_%05d_done" % (wd, p_id)  ))
        parameters =  {
                       "job_id": p_id, 
                       "prefix": db_prefix,
                       "out_file_fn": out_file,
                       #"out_done": out_done,
                       "config": config}
        cons_task = parameters
        tasks[p_id] = (merge_task, cons_task)

    return tasks

def run_falcon_build_pdb(input_files, output_files):
    print('output_files: %s' %(repr(output_files)))
    cwd = os.getcwd()
    odir = os.path.realpath(os.path.abspath(os.path.dirname(output_files[0])))
    if True: #debug
        if cwd != odir:
            raise Exception('%r != %r' %(cwd, odir))
    i_json_config_fn, i_fofn_fn = input_files
    print('output_files: %s' %repr(output_files))
    run_daligner_jobs_fn, = output_files
    #o_fofn_fn, = output_files
    config = _get_config_from_json_fileobj(open(i_json_config_fn))
    script_fn = os.path.join(odir, 'prepare_pdb.sh')
    job_done_fn = os.path.join(odir, 'job_done')
    support.build_pdb(i_fofn_fn, cwd, config, job_done_fn, script_fn, run_daligner_jobs_fn)
    run_cmd('bash %s' %script_fn, sys.stdout, sys.stderr, shell=False)

def _linewrap_fasta(ifn, ofn):
    with FastaIO.FastaReader(ifn) as fa_in:
        with FastaIO.FastaWriter(ofn) as fa_out:
            for rec in fa_in:
                fa_out.writeRecord(rec)

def run_falcon_asm(input_files, output_files):
    i_json_config_fn, i_fofn_fn = input_files
    o_fasta_fn, = output_files
    cwd = os.getcwd()
    pread_dir = os.path.dirname(i_fofn_fn)
    db_file = os.path.join(pread_dir, 'preads.db')
    job_done = os.path.join(cwd, 'job_done')
    config = _get_config_from_json_fileobj(open(i_json_config_fn))
    script_fn =  os.path.join(cwd ,"run_falcon_asm.sh")
    args = {
        'pread_dir': pread_dir,
        'db_file': db_file,
        'config': config,
        'job_done': job_done,
        'script_fn': script_fn,
    }
    support.run_falcon_asm(**args)
    run_cmd('bash %s' %script_fn, sys.stdout, sys.stderr, shell=False)
    _linewrap_fasta('p_ctg.fa', o_fasta_fn)
    say('Finished run_falcon_asm(%s, %s)' %(repr(input_files), repr(output_files)))

