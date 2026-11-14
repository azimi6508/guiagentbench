"""Public journey and sealed behavioral test for aura-013-caption-preview-size."""
CHECKPOINTS = 3

def _step(page, action):
    import time
    from urllib.parse import urlsplit
    kind = action['action']
    if kind == 'click':
        page.mouse.click(action['x'], action['y'])
    elif kind == 'hover':
        page.mouse.move(action['x'], action['y'])
    elif kind == 'scroll':
        page.mouse.wheel(action['dx'], action['dy'])
    elif kind == 'press':
        page.keyboard.press(action['key'])
    elif kind == 'type':
        origin = urlsplit(page.url)
        text = action['text'].replace('http://app:8000', origin.scheme+'://'+origin.netloc)
        page.keyboard.insert_text(text)
    elif kind == 'reload':
        page.reload(wait_until='domcontentloaded')
    else:
        raise ValueError('Unknown frozen action')
    time.sleep(0.35)

def _assertions(page, checks):
    failures = []
    for check in checks:
        kind, selector = check['kind'], check['selector']
        value = check.get('value')
        locator = page.locator(selector)
        count = locator.count()
        item = locator.first
        actual = None
        if kind == 'count':
            actual = count
            good = count == value
        elif kind == 'visible':
            actual = count > 0 and item.is_visible()
            good = actual
        elif kind == 'hidden':
            actual = count == 0 or not item.is_visible()
            good = actual
        elif not count:
            good = False
            actual = '<missing>'
        elif kind in {'text', 'text_not_contains'}:
            actual = item.inner_text(timeout=1500)
            good = value not in actual if kind == 'text_not_contains' else (actual == value if check.get('exact') else value in actual)
        elif kind == 'texts':
            actual = locator.all_text_contents()
            good = actual == value
        elif kind == 'value':
            actual = item.input_value(timeout=1500)
            good = actual == str(value)
        elif kind in {'attribute', 'attribute_contains'}:
            actual = item.get_attribute(check['name'], timeout=1500)
            good = str(value) in (actual or '') if kind.endswith('_contains') else actual == value
        elif kind in {'css', 'css_contains'}:
            actual = item.evaluate('(el,key)=>getComputedStyle(el).getPropertyValue(key).trim()', check['name'])
            good = str(value) in actual if kind.endswith('_contains') else actual == str(value)
        elif kind == 'focused':
            actual = item.evaluate('el=>el===document.activeElement')
            good = actual
        else:
            raise ValueError('Unknown assertion kind: '+kind)
        if not good:
            failures.append({'kind':kind,'selector':selector,'expected':value,'actual':actual})
    assert not failures, __import__('json').dumps(failures, ensure_ascii=False)

ACTIONS = [{'action': 'click', 'x': 1159, 'y': 40}, {'action': 'click', 'x': 147, 'y': 326}, {'action': 'click', 'x': 599, 'y': 440}, {'action': 'click', 'x': 640, 'y': 446}]
CHECKS = [{'kind': 'text', 'selector': '#setting-value-captionSize', 'value': 'Large'}, {'kind': 'css', 'selector': 'html', 'value': '2.5rem', 'name': '--caption-font'}]

def test_behavior(page, checkpoint):
    page.get_by_role('button', name='Settings', exact=True).wait_for(state='visible')
    page.wait_for_timeout(700)
    checkpoint('The prepared AURA library is ready for the requested workflow.')
    for index, action in enumerate(ACTIONS, 1):
        _step(page, action)
        if index == 2:
            checkpoint('The requested workflow is in progress.')
    checkpoint('The final user-visible state is ready for inspection.')
    _assertions(page, CHECKS)
