import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'app'))

from app import app

with app.test_request_context('/'):
    from flask import render_template
    
    rendered = render_template(
        'index.html',
        current_buddhist_year='2569',
        staff_logged_in=False,
        is_admin=False
    )
    
    # Find the nav section
    start = rendered.find('<nav class="top-nav">')
    end = rendered.find('</nav>', start) + len('</nav>')
    
    print("=== NAVIGATION MENU ===")
    print(rendered[start:end])
