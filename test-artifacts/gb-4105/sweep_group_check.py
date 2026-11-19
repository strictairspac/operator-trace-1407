import sys
sys.path.insert(0, '/workspace/backend')
import src.services.sweeps as sw

# Direct check of the grouping helpers: boundaries and results of published
# intervals are never rewritten; merged members simply point at a group root.
def iv(i, status, lo, hi, root=None, fp='A'):
    return {'index': i, 'status': status, 'lower': lo, 'upper': hi,
            'lower_inclusive': False, 'upper_inclusive': True,
            'threshold': lo if lo is not None else 0,
            'fingerprint': fp, 'output_rows': 1, 'checksum': fp,
            'preview': [], 'operators': [], 'merged_into': root, 'error': None}

intervals = [iv(0, 'published', None, 10), iv(1, 'merged', 10, 20, 0),
             iv(2, 'published', 20, 30, fp='B'), iv(3, 'merged', 30, 40, 2),
             iv(4, 'merged', 40, None, 2, fp='B')]
groups = sw._groups(intervals)
assert [(g['root_index'], g['member_indexes']) for g in groups] == [(0, [0, 1]), (2, [2, 3, 4])], groups
assert groups[0]['upper'] == 20 and groups[1]['upper'] is None
before = [(i['lower'], i['upper']) for i in intervals]

# bridging: a retried interval that matches both neighbouring groups joins them
bridge = [iv(0, 'published', None, 10), iv(1, 'merged', 10, 20, 0),
          iv(2, 'merged', 20, 30, 3), iv(3, 'published', 30, None)]
root = sw._root_of(bridge, 1)   # left neighbour's group
sw._repoint(bridge, sw._root_of(bridge, 3), root)   # bridge the right group into it
bridge[2]['merged_into'] = root   # the retried interval itself
groups = sw._groups(bridge)
assert len(groups) == 1 and groups[0]['member_indexes'] == [0, 1, 2, 3], groups
assert (groups[0]['lower'], groups[0]['upper']) == (None, None)
assert [(i['lower'], i['upper']) for i in bridge] == [(None, 10), (10, 20), (20, 30), (30, None)]
print('group helpers ok')
