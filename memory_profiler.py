#!/usr/bin/env python
# coding: utf-8


import sys
import os
import logging as log
import threading
import multiprocessing as mp
import re
import time
import datetime
import json
import csv
import socket
import textwrap
from collections import deque
from fabric.api import run, local, execute, env
from fabric.contrib import project


class Stack():
    def __init__(self, iterable=[], maxlen=0):
        self.maxlen = maxlen
        self.container = deque(iterable, maxlen=maxlen)
        self.penultimate_storage = None

    def __str__(self):
        ret = "Stack("
        size = self.size()

        for i in xrange(size):
            ret += repr(self.container[i])
            if i != size - 1:
                ret += ","

        ret += ")"

        return ret

    def __repr__(self):
        return self.__str__()

    def push(self, value):
        self.penultimate_storage = self.last()
        self.container.append(value)

    def pop(self):
        try:
            return self.container.pop()
        except IndexError:
            return None

    def clear(self):
        self.container.clear()

    def size(self):
        return len(self.container)

    def get(self, index):
        try:
            return self.container[index]
        except IndexError:
            return None

    def first(self):
        return self.get(0)

    def last(self):
        return self.get(-1)

    def penultimate(self):
        if self.penultimate_storage:
            return self.penultimate_storage
        else:
            return self.get(-2)


# 結果を10件くらい保存しておく
class MemoryProfileDataContainer():
    def __init__(self, data_dir, data_filename="", to_csv=False):
        self.data_dir = data_dir
        self.data_filename = data_filename
        self.to_csv = to_csv

        self.container = Stack(maxlen=10)
        self.label_max_size = 0

        self.setDataPath()
        self.setupSerializeFile()

    def __del__(self):
        self.fs.close()

    def __repr__(self):
        if self.container.size() == 0:
            return ""

        ret = ""
        last_items = self.container.last()
        penultimate_items = self.container.penultimate()

        diff_items = self.diff(last_items, penultimate_items)

        if self.label_max_size == 0:
            self.calcLabelMaxSize(last_items)

        for item in last_items:
            diff_str = ""
            if item["label"] in diff_items:
                if diff_items[ item["label"] ] != 0:
                    diff_str = " (%d)" % diff_items[ item["label"] ]

            if isinstance(item["value"], int):
                fmt = "%s %-" + str(self.label_max_size) + "s %d %s\n"
            else:
                fmt = "%s %-" + str(self.label_max_size) + "s %s %s\n"

            ret += fmt % (
                datetime.datetime.fromtimestamp(item["time"]).isoformat(),
                item["label"],
                item["value"],
                diff_str)

        return ret

    def __str__(self):
        return self.__repr__()

    def setDataPath(self):
        if not self.data_filename:
            if not self.to_csv:
                ext = "json"
            else:
                ext = "csv"

            self.data_filename = "mprof_%s.%s" % (
                datetime.datetime.now().strftime("%Y%m%d-%H%M%S"),
                ext)

        self.data_path = "%s/%s" % (self.data_dir, self.data_filename)

        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir)

    def setupSerializeFile(self):
        self.fs = open(self.data_path, "w+b")
        self.init_json = False

    def calcLabelMaxSize(self, sample_items):
        self.label_max_size = len(reduce(
            lambda a, b: a if len(a) >= len(b) else b,
            [ item["label"] for item in sample_items ]))

    def push(self, data):
        self.container.push(data)

    def diff(self, new, old):
        if not new or not old:
            return {}

        if len(new) != len(old):
            return {}

        ret = {}
        for i in xrange(len(new)):
            new_value = new[i]["value"]
            old_value = old[i]["value"]
            label = new[i]["label"]

            if not ( \
                isinstance(new_value, int) \
                or isinstance(new_value, float) \
                or isinstance(new_value, long) \
                or isinstance(old_value, int) \
                or isinstance(old_value, float) \
                or isinstance(old_value, long) \
            ):
                continue

            diff_value = new_value - old_value
            ret[label] = diff_value

        return ret

    def serialize(self):
        if not self.to_csv:
            self.serialize_json()
        else:
            self.serialize_csv()

    def serialize_json(self):
        first_line = False

        items = self.container.last()
        data = { item["label"]: item["value"] for item in items }

        timestamp = items[0]["time"]
        pid = data["PID"]
        procname = data["Procname"]
        hostname = data["Hostname"]

        if not self.init_json:
            out = textwrap.dedent("""
                {
                  "pid": %d,
                  "processName": "%s",
                  "hostName": "%s",
                  "meminfo": [
                  ]
                }
            """ % (pid, procname, hostname)).strip() + "\n"

            self.fs.writelines(out)
            self.fs.flush()

            first_line = True
            self.init_json = True

        out = {
            "timestamp"     : timestamp,
            "systemMemory"  : {
                "memTotal"     : data["MemTotal"],
                "memAvailable" : data["MemFree"],
                "swapTotal"    : data["SwapTotal"],
                "swapFree"     : data["SwapFree"]
            },
            "processMemory" : {
                "vmPeak" : data["VmPeak"],
                "vmSize" : data["VmSize"],
                "vmLck"  : data["VmLck"],
                "vmPin"  : data["VmPin"],
                "vmHWM"  : data["VmHWM"],
                "vmRSS"  : data["VmRSS"],
                "vmData" : data["VmData"],
                "vmStk"  : data["VmStk"],
                "vmExe"  : data["VmExe"],
                "vmLib"  : data["VmLib"],
                "vmPTE"  : data["VmPTE"],
                "vmSwap" : data["VmSwap"]
            }
        }

        comma = ","
        if first_line:
            comma = ""

        tail = "\n  ]\n}\n"
        out_str = "%s\n    %s%s" % (comma, json.dumps(out), tail)

        self.fs.seek(-len(tail), os.SEEK_END)
        self.fs.write(out_str)
        self.fs.flush()

    def serialize_csv(self):
        if not hasattr(self, "csv_writer"):
            self.csv_writer = csv.writer(self.fs, lineterminator="\n")

        for item in self.container.last():
            self.csv_writer.writerow([ item["time"], item["label"], item["value"] ])

        self.fs.flush()


class MemoryProfileThread(mp.Process):
    MonitorSystemItems = (
        "MemTotal", "MemFree", "MemAvailable", "SwapTotal", "SwapFree",
    )

    MonitorProcItems = (
        "VmPeak", "VmSize", "VmLck", "VmPin", "VmHWM",
        "VmRSS", "VmData", "VmStk", "VmExe", "VmLib",
        "VmPTE", "VmSwap",
    )

    @staticmethod
    def findPid(procname):
        pattern = re.compile(procname)
        target_pids = []
        current_pids = [ pid for pid in os.listdir("/proc") if pid.isdigit() ]

        for pid in current_pids:
            try:
                cmdline_path = os.path.join("/proc", pid, "cmdline")
                cmdline = open(cmdline_path, "rb").read()

                if pattern.search(cmdline):
                    target_pids.append(int(pid))

            except IOError:
                # proc has already terminated
                continue

        # to remove pid myself
        try:
            mypid = os.getpid()
            target_pids.remove(mypid)
        except ValueError:
            pass

        if len(target_pids) == 0:
            raise RuntimeError("Not found target process \"%s\"" % procname)

        elif len(target_pids) >= 2:
            spids = " ".join([ str(t) for t in target_pids ])
            raise RuntimeError("Duplicate process: %s" % spids)

        return int(target_pids[0])

    @staticmethod
    def findProcname(pid):
        with open("/proc/%d/cmdline" % pid) as f:
            procname = f.read().strip().split("\0")[0]
            return procname

    def __init__(self, lock, pid=-1, procname=None, data_dir=None, data_filename=None, to_csv=False, interval=1):
        super(MemoryProfileThread, self).__init__()

        self.daemon = True

        self.lock = lock
        self.interval = interval
        self.data_dir = data_dir
        self.data_filename = data_filename

        self.setPID(pid, procname)
        self.setHostname()

        self.mpdc = MemoryProfileDataContainer(self.data_dir, self.data_filename, to_csv)

    def setPID(self, pid, procname):
        if pid == -1 and procname == None:
            raise RuntimeError("No pid or procname found")

        elif pid == -1 and procname != None:
            self.procname = procname
            self.tpid = MemoryProfileThread.findPid(procname)

        elif pid != -1:
            self.tpid = int(pid)

        if not hasattr(self, "procname") or not self.procname:
            self.procname = MemoryProfileThread.findProcname(self.tpid)

    def setHostname(self):
        self.host = socket.gethostname()

    def formatLine(self, line, unixtime):
        _line = line \
            .strip() \
            .replace("\t", "") \
            .replace(" ", "")

        label, value_temp1 = _line.split(":")
        value_temp2, unit = value_temp1[:-2], value_temp1[-2:]
        value = 0

        if unit == "kB":
            value = int(value_temp2) * 1024
        else:
            value = int(value_temp1)

        return {
            "time": unixtime,
            "label": label,
            "value": value,
        }

    def getMonitorItems(self, unixtime, procfile, monitor_items):
        find_items = []

        with open(procfile, "r") as f:
            lines = f.readlines()
            for line in lines:
                for mi in monitor_items:
                    if line.find(mi) == 0:
                        find_items.append(self.formatLine(line, unixtime))

        return find_items

    def getIdentItems(self, unixtime):
        return [{
                "time": unixtime,
                "label": "PID",
                "value": self.tpid
            }, {
                "time": unixtime,
                "label": "Procname",
                "value": self.procname,
            }, {
                "time": unixtime,
                "label": "Hostname",
                "value": self.host,
            }]

    def _run(self):
        while True:
            unixtime = int(time.mktime(datetime.datetime.now().timetuple()))

            data_ident = self.getIdentItems(unixtime)

            data_system = self.getMonitorItems(
                unixtime=unixtime,
                procfile="/proc/meminfo",
                monitor_items=MemoryProfileThread.MonitorSystemItems)

            data_proc = self.getMonitorItems(
                unixtime=unixtime,
                procfile="/proc/%d/status" % self.tpid,
                monitor_items=MemoryProfileThread.MonitorProcItems)

            data_all = data_ident + data_system + data_proc

            self.mpdc.push(data_all)
            self.mpdc.serialize()

            with self.lock:
                sys.stdout.write(str(self.mpdc) + "\n")

            time.sleep(self.interval)

    def run(self):
        try:
            self._run()
        except KeyboardInterrupt:
            return


def logging(
        procname,
        pid,
        data_dir,
        data_filename,
        to_csv
):
    lock = mp.Lock()

    t = MemoryProfileThread(
        lock          = lock,
        procname      = procname,
        pid           = pid,
        data_dir      = data_dir,
        data_filename = data_filename,
        to_csv        = to_csv)

    t.start()

    while True:
        try:
            t.join(1)
        except KeyboardInterrupt:
            log.info("KeyboardInterrupt")
            t.terminate()
            break


def remote(
        procname,
        pid,
        data_dir,
        data_filename,
        to_csv,
        remote_host,
        remote_dir,
        remote_user="",
        remote_password=""
):
    def remoteTask(remote_prof_cmd, remote_close_cmd):
        log.info("remoteTask")

        try:
            run(remote_prof_cmd)
        finally:
            local(remote_close_cmd)

    env.use_ssh_config = True
    env.hosts = [ remote_host ]
    env.host_string = remote_host
    env.user = remote_user
    env_password = remote_password

    cwd, project_exec = os.path.split(os.path.abspath(sys.argv[0]))

    to_csv_arg = ""
    if to_csv:
        to_csv_arg = "-C"

    remote_prof_cmd = "python %s/%s/%s -c %s -p %d -d %s %s" % (
        remote_dir,
        cwd.split("/")[-1],
        project_exec,
        procname,
        pid,
        data_dir,
        to_csv_arg)

    remote_close_cmd = "mkdir -p %s && rsync -av %s:%s/%s %s" % (
        data_dir,
        remote_host,
        data_dir,
        data_filename,
        data_dir)

    project.rsync_project(
        local_dir=cwd,
        remote_dir=remote_dir,
        exclude=[ "*.pyc", "*~", "*.swp", ".git*" ])

    execute(remoteTask, remote_prof_cmd, remote_close_cmd)

    log.info("done")


def getarg():
    import argparse
    parser = argparse.ArgumentParser(add_help=False)

    parser.add_argument("-c", "--procname", type=str, default=None, help="process name")
    parser.add_argument("-p", "--pid", type=int, default=-1, help="process id")
    parser.add_argument("-d", "--data-dir", type=str, default="mprof_data", help="data dir")
    parser.add_argument("-C", "--to-csv", action="store_true", help="output csv format")
    parser.add_argument("-r", "--enable-remote", action="store_true", help="enable remote")
    parser.add_argument("-h", "--remote-host", type=str, help="remote host")
    parser.add_argument("-t", "--remote-dir", type=str, default="~", help="remote dir")
    parser.add_argument("-U", "--remote-user", type=str, help="remote user")
    parser.add_argument("-P", "--remote-password", type=str, help="remote password")
    parser.add_argument("--help", action="help")

    args = parser.parse_args()
    return args


def main():
    args = getarg()

    log.info("start logging \"%s (%d)\"" % (args.procname, args.pid))

    if not args.to_csv:
        ext = "json"
    else:
        ext = "csv"

    data_filename = "mprof_%s.%s" % (datetime.datetime.now().strftime("%Y%m%d-%H%M%S"), ext)

    if not args.enable_remote:
        logging(
            procname      = args.procname,
            pid           = args.pid,
            data_dir      = args.data_dir,
            data_filename = data_filename,
            to_csv        = args.to_csv)

    else:
        log.info("connecting remote host \"%s\"" % args.remote_host)
        remote(
            procname        = args.procname,
            pid             = args.pid,
            data_dir        = args.data_dir,
            data_filename   = data_filename,
            to_csv          = args.to_csv,
            remote_host     = args.remote_host,
            remote_dir      = args.remote_dir,
            remote_user     = args.remote_user,
            remote_password = args.remote_password)


if __name__ == "__main__":
    log.basicConfig(
        format="[%(asctime)s][%(levelname)s] %(message)s",
        datefmt="%Y/%m/%d %H:%M:%S",
        level=log.DEBUG)

    main()


