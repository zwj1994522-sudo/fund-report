import requests, time, os

TOKEN = os.environ['TOKEN']
headers = {'Authorization': f'token {TOKEN}', 'Accept': 'application/vnd.github+json'}

r = requests.get('https://api.github.com/repos/zwj1994522-sudo/fund-report/git/refs/heads/trigger-report', headers=headers)
sha = r.json()['object']['sha']

r2 = requests.get(f'https://api.github.com/repos/zwj1994522-sudo/fund-report/git/commits/{sha}', headers=headers)
tree_sha = r2.json()['tree']['sha']

r3 = requests.post('https://api.github.com/repos/zwj1994522-sudo/fund-report/git/commits', headers=headers,
    json={'message': f'auto-trigger {int(time.time())}', 'tree': tree_sha, 'parents': [sha]})
new_sha = r3.json()['sha']

r4 = requests.patch('https://api.github.com/repos/zwj1994522-sudo/fund-report/git/refs/heads/trigger-report',
    headers=headers, json={'sha': new_sha, 'force': True})
print(f'Trigger HTTP {r4.status_code}')
