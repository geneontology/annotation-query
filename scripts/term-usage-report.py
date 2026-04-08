####
#### Invocation examples:
####
#### Dump a TSV of term usages from Ubergraph, scanning geneontology/annotation-query issue contents for the last seven days with the label "term_usage":
####
####   python3 ./scripts/term-usage-report.py geneontology/annotation-query 7 --number 94 --label term_usage --output /tmp --verbose
####

import logging
import sys
import re
import requests
import json
import datetime
import argparse
import os
import subprocess
from pytz import timezone

###
### Global preamble.
###

## Logger basic setup w/killer error.
logging.basicConfig(level=logging.INFO)
LOG = logging.getLogger('term-usage-report')
LOG.setLevel(logging.WARNING)
def die_screaming(instr):
    """Make sure we exit in a way that will get Jenkins's attention."""
    LOG.error(instr)
    sys.exit(1)

## Get arge sorted.
parser = argparse.ArgumentParser()
parser.add_argument('repo_name')
parser.add_argument('duration_in_days')
parser.add_argument('-t', '--todays_date', help="Override the date to start 'looking back' from. Date must be in ISO format e.g. '2022-08-16'")
parser.add_argument('-n', '--number',  help='GH issue to filter for')
parser.add_argument('-l', '--label',  help='GH label to filter for')
parser.add_argument('-o', '--output',  help='Output directory')
parser.add_argument('-v', '--verbose', action='store_true', help='More verbose output')

args = parser.parse_args()

## Verbose messages or not.
if args.verbose:
    LOG.setLevel(logging.INFO)
LOG.info('Verbose: on')

if not args.output:
    die_screaming('need an output directory')
LOG.info('Will output to: ' + args.output)

if not args.number:
    die_screaming('need an issue number')
LOG.info('Will filter for issue: ' + args.number)

if not args.label:
    die_screaming('need an issue label')
LOG.info('Will filter for issue label: ' + args.label)

## Global. This was here before I got here--don't judge.
collected_terms = []

###
### Helpers.
###

## Append to global variable, including print information.
def collect_terms(issues, number: str, event_type: str, printed_ids: set):

    cis = []

    for issue in issues:
        if (issue['state'] == 'open') and (int(number) == issue['number']):
            has_label_p = False
            if len(issue['labels']) > 0 :
                for label in issue['labels']:
                    if label['name'] == args.label:
                        has_label_p = True
            matches = re.findall("GO:[0-9]+", issue['body'])
            if has_label_p and len(matches) > 0:
                matches = re.findall("GO:[0-9]+", issue['body'])
                for m in matches:
                    cis.append(m)
    ## Dedupe and sort.
    cis = list(dict.fromkeys(cis))
    cis.sort()
    return cis

## Pull issues from GH.
def get_issues(repo: str, event_type: str, start_date: str):
    url = "https://api.github.com/search/issues?q=repo:{}+{}:=>{}+is:issue&type=Issues&per_page=100".format(repo, event_type, start_date)
    resp = requests.get(url)
    if resp.status_code == 200:
        resp_objs = json.loads(resp.content)
        issues = resp_objs.get("items", [])
        return issues
    else:
        raise Exception("HTTP error status code: {} for url: {}".format(resp.status_code, url))

## Get term usages from Ubergraph via runoak.
def get_term_usages(terms):
    cmd = ['runoak', '-i', 'ubergraph:', 'usages'] + terms
    LOG.info('Running command: ' + ' '.join(cmd))
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except FileNotFoundError:
        die_screaming('runoak not found on PATH. Install oaklib: pip install oaklib')
    except subprocess.TimeoutExpired:
        die_screaming('runoak usages timed out after 300 seconds')
    if result.returncode != 0:
        die_screaming('runoak usages failed (exit code ' + str(result.returncode) + '): ' + result.stderr)
    return result.stdout.rstrip()

###
### Main.
###

## Start.
if __name__ == "__main__":

    ## Get date/time for GH interactions/filtering.
    today_time = datetime.datetime.now(tz=timezone('US/Pacific'))
    if args.todays_date:
        try:
            today_time = datetime.datetime.strptime(args.todays_date, '%Y-%m-%d')
        except ValueError:
            raise ValueError("Incorrect data format, todays_date should be YYYY-MM-DD")
    yesterday_time = today_time - datetime.timedelta(int(args.duration_in_days))
    yesterday_time_str = yesterday_time.isoformat()

    ## Get times/dates for display.
    today = today_time.strftime("%Y-%m-%d")
    yesterday = yesterday_time.strftime("%Y-%m-%d")

    ## Pull in created and updated issues.
    new_issues = get_issues(args.repo_name, "created", yesterday_time_str)

    ## Filter and sort the items in global collected_terms([]).
    repo_name = args.repo_name
    if "/" in repo_name:
        repo_name = repo_name.rsplit("/", maxsplit=1)[-1]
    ids = set()
    collected_terms = collected_terms + collect_terms(new_issues, args.number, "New", ids)

    ## Check that we got something.
    if len(collected_terms) == 0:
        die_screaming('no terms found in collected_terms')

    ## All reports to single file.
    outfile = "-".join(collected_terms)

    ## Truncate length if too long:
    ## https://github.com/geneontology/go-annotation/issues/4495
    if len(outfile) > 100:
        outfile = outfile[0:98]
        outfile = outfile + '_etc'
        LOG.info('output list truncation: ' + outfile)

    ## Continue assembly.
    outfile = outfile.replace(':','_') + '.tsv'
    outfile = args.output + '/' + 'term_usage_' + outfile
    LOG.info('output to file: ' + outfile)

    ## Get usages for all terms at once.
    usage_output = get_term_usages(collected_terms)

    ## Filter out GO-internal usages (used_by_id starting with "GO:").
    ## We only care about cross-ontology references for obsoletion review.
    ## Also filter to only include rows where context is RELATIONSHIP_OBJECT.
    lines = usage_output.split("\n") if usage_output else []
    header = "used_id\tused_by_id\tpredicate\tsource\tdataset\tcontext\taxiom\tdescription"
    data_lines = []
    for l in lines:
        if not l.strip() or l.startswith("used_id"):
            continue
        cols = l.split("\t")
        if len(cols) >= 2 and cols[1].startswith("GO:"):
            continue
        if len(cols) < 6 or cols[5] != "UsageContext.RELATIONSHIP_OBJECT":
            continue
        data_lines.append(l)
    saw_a_result_p = len(data_lines) > 0

    ## Final writeout.
    with open(outfile, 'w+') as fhandle:
        fhandle.write(header)
        fhandle.write("\n")
        for l in data_lines:
            fhandle.write(l)
            fhandle.write("\n")

    ## Rename as empty if did not see any results.
    if saw_a_result_p == False:
        LOG.info('No results found, so renaming as EMPTY.')
        os.rename(outfile, os.path.join(os.path.split(outfile)[0], 'EMPTY_' + os.path.basename(outfile)))
    else:
        LOG.info('Results found, no renaming.')
