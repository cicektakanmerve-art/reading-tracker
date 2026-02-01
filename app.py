import os
import re
import json
import requests
from urllib.parse import urlparse
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from bs4 import BeautifulSoup
from models import db, ReadingMaterial, Tag, Status, Note

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///reading_tracker.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

# Custom Jinja2 filter for parsing JSON
@app.template_filter('from_json')
def from_json_filter(value):
    """Parse JSON string in templates."""
    if not value:
        return []
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return []

def init_default_statuses():
    """Create default statuses if none exist."""
    if Status.query.count() == 0:
        defaults = [
            ('to_read', 'To Read', 'blue', 1),
            ('reading', 'Reading', 'orange', 2),
            ('completed', 'Completed', 'green', 3),
            ('on_hold', 'On Hold', 'pink', 4),
            ('dropped', 'Dropped', 'gray', 5),
        ]
        for name, display, color, pos in defaults:
            db.session.add(Status(name=name, display_name=display, color=color, position=pos))
        db.session.commit()

with app.app_context():
    db.create_all()
    init_default_statuses()


@app.route('/')
def index():
    search_query = request.args.get('q', '').strip()
    status_filter = request.args.get('status', '')
    tag_filters = request.args.getlist('tags')  # Multiple tags support

    query = ReadingMaterial.query

    if search_query:
        search_term = f'%{search_query}%'
        query = query.filter(
            db.or_(
                ReadingMaterial.title.ilike(search_term),
                ReadingMaterial.notes.ilike(search_term)
            )
        )

    if status_filter:
        query = query.filter(ReadingMaterial.status_id == int(status_filter))

    if tag_filters:
        # Filter items that have ALL selected tags
        for tag_name in tag_filters:
            query = query.filter(
                ReadingMaterial.tags.any(Tag.name == tag_name)
            )

    items = query.order_by(ReadingMaterial.updated_at.desc()).all()
    tags = Tag.query.order_by(Tag.name).all()
    statuses = Status.query.order_by(Status.position).all()

    # Group items by status
    grouped_items = []
    status_map = {}
    for status in statuses:
        group = {
            'status': status,
            'entries': []
        }
        grouped_items.append(group)
        status_map[status.id] = group

    # Add a group for items without status
    no_status_group = {
        'status': None,
        'entries': []
    }
    status_map[None] = no_status_group

    for item in items:
        status_map[item.status_id]['entries'].append(item)

    # Add no-status group at the end if it has entries
    if no_status_group['entries']:
        grouped_items.append(no_status_group)

    return render_template('index.html',
                         items=items,
                         grouped_items=grouped_items,
                         tags=tags,
                         statuses=statuses,
                         current_status=status_filter,
                         current_tags=tag_filters,
                         search_query=search_query)


@app.route('/api/search')
def api_search():
    search_query = request.args.get('q', '').strip()
    status_filter = request.args.get('status', '')
    tag_filters = request.args.getlist('tags')  # Multiple tags support

    query = ReadingMaterial.query

    if search_query:
        search_term = f'%{search_query}%'
        query = query.filter(
            db.or_(
                ReadingMaterial.title.ilike(search_term),
                ReadingMaterial.notes.ilike(search_term)
            )
        )

    if status_filter:
        query = query.filter(ReadingMaterial.status_id == int(status_filter))

    if tag_filters:
        # Filter items that have ALL selected tags
        for tag_name in tag_filters:
            query = query.filter(
                ReadingMaterial.tags.any(Tag.name == tag_name)
            )

    items = query.order_by(ReadingMaterial.updated_at.desc()).all()
    statuses = Status.query.order_by(Status.position).all()

    # Group items by status
    grouped = {}
    for status in statuses:
        grouped[status.id] = {
            'status_id': status.id,
            'status_name': status.display_name,
            'status_color': status.color,
            'items': []
        }
    grouped[0] = {
        'status_id': 0,
        'status_name': 'No Status',
        'status_color': 'gray',
        'items': []
    }

    for item in items:
        key = item.status_id if item.status_id else 0
        grouped[key]['items'].append({
            'id': item.id,
            'title': item.title,
            'link': item.link,
            'image_url': item.image_url,
            'status_display': item.status_display,
            'status_color': item.status_color,
            'status_id': item.status_id,
            'chapter_current': item.chapter_current,
            'chapter_total': item.chapter_total,
            'progress_percent': item.progress_percent,
            'tags': [{'id': tag.id, 'name': tag.name, 'color': tag.color or 'gray'} for tag in item.tags]
        })

    # Return only groups that have items, maintaining order
    result = []
    for status in statuses:
        if grouped[status.id]['items']:
            result.append(grouped[status.id])
    if grouped[0]['items']:
        result.append(grouped[0])

    return jsonify(result)


@app.route('/add', methods=['GET', 'POST'])
def add():
    statuses = Status.query.order_by(Status.position).all()

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        if not title:
            flash('Title is required', 'error')
            return redirect(url_for('add'))

        status_id = request.form.get('status_id')
        item = ReadingMaterial(
            title=title,
            link=request.form.get('link', '').strip() or None,
            image_url=request.form.get('image_url', '').strip() or None,
            status_id=int(status_id) if status_id else None,
            chapter_current=int(request.form.get('chapter_current', 0) or 0),
            chapter_total=int(request.form.get('chapter_total') or 0) or None,
            notes=request.form.get('notes', '').strip() or None,
            scraped_comments=request.form.get('scraped_comments', '').strip() or None,
            total_comments_count=int(request.form.get('total_comments_count') or 0) or None
        )

        # Handle tags
        tag_names = request.form.get('tags', '').strip()
        if tag_names:
            for tag_name in tag_names.split(','):
                tag_name = tag_name.strip()
                if tag_name:
                    # Case-insensitive search for existing tag
                    tag = Tag.query.filter(Tag.name.ilike(tag_name)).first()
                    if not tag:
                        tag = Tag(name=tag_name, color=Tag.random_color())
                        db.session.add(tag)
                    item.tags.append(tag)

        db.session.add(item)
        db.session.commit()
        flash('Reading material added successfully', 'success')
        return redirect(url_for('index'))

    return render_template('form.html',
                         item=None,
                         statuses=statuses)


@app.route('/edit/<int:id>', methods=['GET', 'POST'])
def edit(id):
    item = ReadingMaterial.query.get_or_404(id)
    statuses = Status.query.order_by(Status.position).all()

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        if not title:
            flash('Title is required', 'error')
            return redirect(url_for('edit', id=id))

        status_id = request.form.get('status_id')
        item.title = title
        item.link = request.form.get('link', '').strip() or None
        item.image_url = request.form.get('image_url', '').strip() or None
        item.status_id = int(status_id) if status_id else None
        item.chapter_current = int(request.form.get('chapter_current', 0) or 0)
        item.chapter_total = int(request.form.get('chapter_total') or 0) or None
        item.notes = request.form.get('notes', '').strip() or None
        item.scraped_comments = request.form.get('scraped_comments', '').strip() or None
        item.total_comments_count = int(request.form.get('total_comments_count') or 0) or None

        # Handle tags - clear and re-add
        item.tags.clear()
        tag_names = request.form.get('tags', '').strip()
        if tag_names:
            for tag_name in tag_names.split(','):
                tag_name = tag_name.strip()
                if tag_name:
                    # Case-insensitive search for existing tag
                    tag = Tag.query.filter(Tag.name.ilike(tag_name)).first()
                    if not tag:
                        tag = Tag(name=tag_name, color=Tag.random_color())
                        db.session.add(tag)
                    item.tags.append(tag)

        db.session.commit()
        flash('Reading material updated successfully', 'success')
        return redirect(url_for('index'))

    return render_template('form.html',
                         item=item,
                         statuses=statuses)


@app.route('/view/<int:id>')
def view(id):
    item = ReadingMaterial.query.get_or_404(id)
    notes = item.note_entries.order_by(Note.created_at.desc()).all()
    statuses = Status.query.order_by(Status.position).all()
    return render_template('view.html', item=item, notes=notes, statuses=statuses)


@app.route('/view/<int:id>/add-note', methods=['POST'])
def add_note(id):
    item = ReadingMaterial.query.get_or_404(id)
    content = request.form.get('content', '').strip()

    if not content:
        flash('Note content is required', 'error')
        return redirect(url_for('view', id=id))

    note = Note(content=content, reading_material_id=item.id)
    db.session.add(note)
    db.session.commit()
    flash('Note added', 'success')
    return redirect(url_for('view', id=id))


@app.route('/note/<int:id>/delete', methods=['POST'])
def delete_note(id):
    note = Note.query.get_or_404(id)
    reading_material_id = note.reading_material_id
    db.session.delete(note)
    db.session.commit()
    flash('Note deleted', 'success')
    return redirect(url_for('view', id=reading_material_id))


@app.route('/note/<int:id>/edit', methods=['POST'])
def edit_note(id):
    note = Note.query.get_or_404(id)
    content = request.form.get('content', '').strip()

    if not content:
        flash('Note content is required', 'error')
    else:
        note.content = content
        db.session.commit()
        flash('Note updated', 'success')

    return redirect(url_for('view', id=note.reading_material_id))


@app.route('/delete/<int:id>', methods=['POST'])
def delete(id):
    item = ReadingMaterial.query.get_or_404(id)
    db.session.delete(item)
    db.session.commit()
    flash('Reading material deleted', 'success')
    return redirect(url_for('index'))


@app.route('/update-progress/<int:id>', methods=['POST'])
def update_progress(id):
    item = ReadingMaterial.query.get_or_404(id)
    chapter = request.form.get('chapter_current', type=int)
    if chapter is not None:
        item.chapter_current = chapter
        db.session.commit()
        flash('Progress updated', 'success')
    return redirect(url_for('index'))


# Status management routes
@app.route('/statuses')
def statuses():
    all_statuses = Status.query.order_by(Status.position).all()
    return render_template('statuses.html', statuses=all_statuses)


@app.route('/statuses/add', methods=['GET', 'POST'])
def add_status():
    if request.method == 'POST':
        name = request.form.get('name', '').strip().lower().replace(' ', '_')
        display_name = request.form.get('display_name', '').strip()
        color = request.form.get('color', 'gray')

        if not name or not display_name:
            flash('Name and display name are required', 'error')
            return redirect(url_for('add_status'))

        if Status.query.filter_by(name=name).first():
            flash('A status with this name already exists', 'error')
            return redirect(url_for('add_status'))

        max_pos = db.session.query(db.func.max(Status.position)).scalar() or 0
        status = Status(name=name, display_name=display_name, color=color, position=max_pos + 1)
        db.session.add(status)
        db.session.commit()
        flash('Status added successfully', 'success')
        return redirect(url_for('statuses'))

    return render_template('status_form.html', status=None)


@app.route('/statuses/edit/<int:id>', methods=['GET', 'POST'])
def edit_status(id):
    status = Status.query.get_or_404(id)

    if request.method == 'POST':
        display_name = request.form.get('display_name', '').strip()
        color = request.form.get('color', 'gray')

        if not display_name:
            flash('Display name is required', 'error')
            return redirect(url_for('edit_status', id=id))

        status.display_name = display_name
        status.color = color
        db.session.commit()
        flash('Status updated successfully', 'success')
        return redirect(url_for('statuses'))

    return render_template('status_form.html', status=status)


@app.route('/statuses/delete/<int:id>', methods=['POST'])
def delete_status(id):
    status = Status.query.get_or_404(id)

    # Check if any reading materials use this status
    if status.reading_materials.count() > 0:
        flash('Cannot delete status that is in use', 'error')
        return redirect(url_for('statuses'))

    db.session.delete(status)
    db.session.commit()
    flash('Status deleted', 'success')
    return redirect(url_for('statuses'))


# Tag management routes
@app.route('/tags')
def tags():
    all_tags = Tag.query.order_by(Tag.name).all()
    # Get usage count for each tag
    tag_data = []
    for tag in all_tags:
        count = tag.reading_materials.count()
        tag_data.append({'tag': tag, 'count': count})
    return render_template('tags.html', tags=tag_data)


@app.route('/tags/add', methods=['GET', 'POST'])
def add_tag():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        color = request.form.get('color') or Tag.random_color()

        if not name:
            flash('Tag name is required', 'error')
            return redirect(url_for('add_tag'))

        # Case-insensitive check for existing tag
        if Tag.query.filter(Tag.name.ilike(name)).first():
            flash('A tag with this name already exists', 'error')
            return redirect(url_for('add_tag'))

        tag = Tag(name=name, color=color)
        db.session.add(tag)
        db.session.commit()
        flash('Tag added successfully', 'success')
        return redirect(url_for('tags'))

    # Pass a random color for the preview default
    return render_template('tag_form.html', tag=None, default_color=Tag.random_color())


@app.route('/tags/edit/<int:id>', methods=['GET', 'POST'])
def edit_tag(id):
    tag = Tag.query.get_or_404(id)

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        color = request.form.get('color', 'gray')

        if not name:
            flash('Tag name is required', 'error')
            return redirect(url_for('edit_tag', id=id))

        # Case-insensitive check for existing tag
        existing = Tag.query.filter(Tag.name.ilike(name)).first()
        if existing and existing.id != tag.id:
            flash('A tag with this name already exists', 'error')
            return redirect(url_for('edit_tag', id=id))

        tag.name = name
        tag.color = color
        db.session.commit()
        flash('Tag updated successfully', 'success')
        return redirect(url_for('tags'))

    return render_template('tag_form.html', tag=tag)


@app.route('/tags/delete/<int:id>', methods=['POST'])
def delete_tag(id):
    tag = Tag.query.get_or_404(id)

    # Check if any reading materials use this tag
    if tag.reading_materials.count() > 0:
        flash('Cannot delete tag that is in use', 'error')
        return redirect(url_for('tags'))

    db.session.delete(tag)
    db.session.commit()
    flash('Tag deleted', 'success')
    return redirect(url_for('tags'))


@app.route('/api/tags')
def api_tags():
    query = request.args.get('q', '').strip()
    if query:
        tags = Tag.query.filter(Tag.name.ilike(f'%{query}%')).order_by(Tag.name).all()
    else:
        tags = Tag.query.order_by(Tag.name).all()
    return jsonify([{'id': tag.id, 'name': tag.name, 'color': tag.color or 'gray'} for tag in tags])


@app.route('/api/tags/<int:id>/color', methods=['POST'])
def api_update_tag_color(id):
    tag = Tag.query.get_or_404(id)
    data = request.get_json()
    color = data.get('color', 'gray')

    if color in Tag.TAG_COLORS:
        tag.color = color
        db.session.commit()
        return jsonify({'id': tag.id, 'name': tag.name, 'color': tag.color})

    return jsonify({'error': 'Invalid color'}), 400


@app.route('/api/tags/create', methods=['POST'])
def api_create_tag():
    data = request.get_json()
    name = data.get('name', '').strip()

    if not name:
        return jsonify({'error': 'Tag name is required'}), 400

    # Case-insensitive check for existing tag
    existing = Tag.query.filter(Tag.name.ilike(name)).first()
    if existing:
        return jsonify({'id': existing.id, 'name': existing.name, 'color': existing.color or 'gray'})

    tag = Tag(name=name, color=Tag.random_color())
    db.session.add(tag)
    db.session.commit()
    return jsonify({'id': tag.id, 'name': tag.name, 'color': tag.color})


@app.route('/api/scrape-url', methods=['POST'])
def api_scrape_url():
    """Scrape metadata from a URL to autofill entry details."""
    data = request.get_json()
    url = data.get('url', '').strip()

    if not url:
        return jsonify({'error': 'URL is required'}), 400

    # Add protocol if missing
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url

    try:
        # Validate URL
        parsed = urlparse(url)
        if not parsed.netloc:
            return jsonify({'error': 'Invalid URL'}), 400

        # Use realistic browser headers to avoid 403 blocks
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Cache-Control': 'max-age=0',
        }

        # Create a session to handle cookies
        session = requests.Session()
        response = session.get(url, headers=headers, timeout=15, allow_redirects=True)

        # If we get a 403, try with cloudscraper (bypasses Cloudflare)
        if response.status_code == 403:
            try:
                import cloudscraper
                scraper = cloudscraper.create_scraper(
                    browser={'browser': 'chrome', 'platform': 'darwin', 'mobile': False}
                )
                response = scraper.get(url, timeout=15)
            except Exception as e:
                # If cloudscraper fails, try simple headers
                simple_headers = {
                    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                }
                response = session.get(url, headers=simple_headers, timeout=15, allow_redirects=True)

        response.raise_for_status()

        # Parse HTML
        soup = BeautifulSoup(response.content, 'html.parser')

        # Extract title
        title = None
        # Try og:title first
        og_title = soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content'].strip()
        # Fall back to <title> tag
        if not title:
            title_tag = soup.find('title')
            if title_tag:
                title = title_tag.get_text().strip()

        # Extract description
        description = None
        # Try og:description first
        og_desc = soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            description = og_desc['content'].strip()
        # Fall back to meta description
        if not description:
            meta_desc = soup.find('meta', attrs={'name': 'description'})
            if meta_desc and meta_desc.get('content'):
                description = meta_desc['content'].strip()

        # Extract image
        image_url = extract_image(soup, response.url)

        # Extract chapter info if it's a manga/novel site
        chapter_info = extract_chapter_info(soup, url, title)

        # Suggest tags based on content
        suggested_tags = extract_suggested_tags(soup, url)

        # Extract comments
        comments_data = extract_comments(soup, response.url)

        return jsonify({
            'success': True,
            'data': {
                'title': title,
                'description': description,
                'image_url': image_url,
                'chapter_current': chapter_info.get('current'),
                'chapter_total': chapter_info.get('total'),
                'suggested_tags': suggested_tags,
                'comments': comments_data.get('comments', []),
                'total_comments': comments_data.get('total', 0),
                'url': response.url  # Return final URL after redirects
            }
        })

    except requests.exceptions.Timeout:
        # Still try to extract from URL
        fallback = extract_from_url(url)
        if fallback:
            return jsonify({'success': True, 'data': fallback, 'partial': True})
        return jsonify({'error': 'Request timed out'}), 408
    except requests.exceptions.RequestException as e:
        # Try fallback extraction from URL pattern
        fallback = extract_from_url(url)
        if fallback:
            return jsonify({'success': True, 'data': fallback, 'partial': True})
        return jsonify({'error': f'Failed to fetch URL: {str(e)}'}), 400
    except Exception as e:
        fallback = extract_from_url(url)
        if fallback:
            return jsonify({'success': True, 'data': fallback, 'partial': True})
        return jsonify({'error': f'Error processing URL: {str(e)}'}), 500


def extract_from_url(url):
    """Extract what we can from the URL itself when scraping fails."""
    try:
        parsed = urlparse(url)
        path = parsed.path
        domain = parsed.netloc.lower()

        # Try to extract title from URL path
        # e.g., /series/the-crazy-young-master-is-obsessed-with-me -> The Crazy Young Master Is Obsessed With Me
        path_parts = path.strip('/').split('/')
        if path_parts:
            # Get the last meaningful part (remove query params)
            slug = path_parts[-1] if path_parts[-1] else (path_parts[-2] if len(path_parts) > 1 else '')
            slug = slug.split('?')[0].split('#')[0]  # Remove query/hash

            if slug:
                # Convert slug to title
                title = slug.replace('-', ' ').replace('_', ' ')
                # Capitalize words
                title = ' '.join(word.capitalize() for word in title.split())

                # Extract tags from URL
                tags = []
                url_lower = url.lower()

                if 'novelupdates' in domain or 'novel' in url_lower:
                    tags.append('novel')
                if 'manga' in url_lower or 'manga' in domain:
                    tags.append('manga')
                if 'webtoon' in url_lower or 'comic' in url_lower:
                    tags.append('webtoon')
                if 'series' in path.lower():
                    tags.append('series')

                # Try to construct image URL for known sites
                image_url = None

                # NovelUpdates - they use a predictable image pattern
                if 'novelupdates.com' in domain and '/series/' in path:
                    # NovelUpdates images are at: https://cdn.novelupdates.com/images/year/month/slug.jpg
                    # We can't know the date, but we can try the API or just leave it
                    # Actually, let's try fetching just the image directly with a different approach
                    image_url = try_fetch_novelupdates_image(slug)

                return {
                    'title': title,
                    'description': None,
                    'image_url': image_url,
                    'chapter_current': None,
                    'chapter_total': None,
                    'suggested_tags': tags[:5],
                    'url': url
                }
    except:
        pass
    return None


def try_fetch_novelupdates_image(slug):
    """Try to fetch image from NovelUpdates using their image CDN patterns."""
    try:
        # NovelUpdates stores images with predictable names
        # Try common CDN patterns
        cdn_patterns = [
            f"https://cdn.novelupdates.com/imgmid/{slug}.jpg",
            f"https://cdn.novelupdates.com/imgmid/{slug}.png",
        ]

        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            'Referer': 'https://www.novelupdates.com/'
        }

        for img_url in cdn_patterns:
            try:
                response = requests.head(img_url, headers=headers, timeout=5, allow_redirects=True)
                if response.status_code == 200:
                    return img_url
            except:
                continue
    except:
        pass
    return None


def extract_image(soup, base_url):
    """Extract cover/banner image from the page."""
    from urllib.parse import urljoin

    image_url = None

    # Try og:image first (most reliable)
    og_image = soup.find('meta', property='og:image')
    if og_image and og_image.get('content'):
        image_url = og_image['content'].strip()

    # Try twitter:image
    if not image_url:
        twitter_image = soup.find('meta', attrs={'name': 'twitter:image'})
        if twitter_image and twitter_image.get('content'):
            image_url = twitter_image['content'].strip()

    # Try schema.org image
    if not image_url:
        schema_image = soup.find('meta', itemprop='image')
        if schema_image and schema_image.get('content'):
            image_url = schema_image['content'].strip()

    # Try common cover image selectors for novel/manga sites
    if not image_url:
        cover_selectors = [
            'img.seriesimg',  # NovelUpdates
            'img.cover',
            'img.book-cover',
            'img.series-cover',
            'img.novel-cover',
            'img.manga-cover',
            '.seriesimg img',
            '.cover img',
            '.book-cover img',
            '[class*="cover"] img',
            '[class*="poster"] img',
            '.entry-content img',
        ]
        for selector in cover_selectors:
            try:
                img = soup.select_one(selector)
                if img and img.get('src'):
                    image_url = img['src']
                    break
            except:
                continue

    # Make relative URLs absolute
    if image_url and not image_url.startswith(('http://', 'https://', 'data:')):
        image_url = urljoin(base_url, image_url)

    return image_url


def extract_chapter_info(soup, url, title):
    """Try to extract chapter information from manga/novel sites."""
    chapter_info = {'current': None, 'total': None}

    # Common patterns for chapter numbers in title or URL
    chapter_patterns = [
        r'[Cc]hapter\s*(\d+)',
        r'[Cc]h\.?\s*(\d+)',
        r'[Ee]pisode\s*(\d+)',
        r'[Ee]p\.?\s*(\d+)',
        r'#(\d+)',
    ]

    text_to_search = f"{title or ''} {url}"

    for pattern in chapter_patterns:
        match = re.search(pattern, text_to_search)
        if match:
            chapter_info['current'] = int(match.group(1))
            break

    # Try to find total chapters from the page
    total_patterns = [
        r'(\d+)\s*[Cc]hapters?\s*(?:total|available)',
        r'[Tt]otal[:\s]+(\d+)',
        r'of\s+(\d+)\s*[Cc]hapters?',
    ]

    page_text = soup.get_text()
    for pattern in total_patterns:
        match = re.search(pattern, page_text)
        if match:
            chapter_info['total'] = int(match.group(1))
            break

    return chapter_info


def extract_suggested_tags(soup, url):
    """Extract suggested tags based on page content and URL."""
    tags = set()

    # Extract from meta keywords
    keywords_meta = soup.find('meta', attrs={'name': 'keywords'})
    if keywords_meta and keywords_meta.get('content'):
        keywords = keywords_meta['content'].split(',')
        for kw in keywords[:8]:
            kw = kw.strip()
            if kw and len(kw) < 30 and len(kw) > 1:
                tags.add(kw.lower())

    # Extract from og:type
    og_type = soup.find('meta', property='og:type')
    if og_type and og_type.get('content'):
        content = og_type['content'].strip().lower()
        if content and content != 'website':
            tags.add(content)

    # Extract genre tags (common on novel/manga sites)
    genre_selectors = [
        '.genre a', '.genres a', '.tag a', '.tags a',
        '[class*="genre"] a', '[class*="tag"] a',
        '.seriesgenre a',  # NovelUpdates
        '.sgenre a',
        'a[href*="genre"]', 'a[href*="tag"]',
        '.info-item a',  # Common manga sites
        '.category a', '.categories a',
    ]

    for selector in genre_selectors:
        try:
            elements = soup.select(selector)
            for el in elements[:10]:
                text = el.get_text().strip().lower()
                if text and len(text) < 30 and len(text) > 1:
                    # Clean up common prefixes
                    text = re.sub(r'^(genre|tag|category)[:\s]*', '', text)
                    if text:
                        tags.add(text)
        except:
            continue

    # Look for genre/type in structured data
    for script in soup.find_all('script', type='application/ld+json'):
        try:
            import json
            data = json.loads(script.string)
            if isinstance(data, dict):
                if 'genre' in data:
                    genres = data['genre'] if isinstance(data['genre'], list) else [data['genre']]
                    for g in genres:
                        if isinstance(g, str):
                            tags.add(g.lower())
        except:
            continue

    # Extract from page content - look for labeled genres
    page_text = soup.get_text()
    genre_patterns = [
        r'[Gg]enre[s]?[:\s]+([A-Za-z,\s]+?)(?:\n|\.|\|)',
        r'[Tt]ype[:\s]+([A-Za-z\s]+?)(?:\n|\.|\|)',
        r'[Cc]ategory[:\s]+([A-Za-z,\s]+?)(?:\n|\.|\|)',
    ]
    for pattern in genre_patterns:
        match = re.search(pattern, page_text)
        if match:
            found = match.group(1).split(',')
            for g in found[:3]:
                g = g.strip().lower()
                if g and len(g) < 25 and len(g) > 1:
                    tags.add(g)

    # Detect common content types from URL
    url_lower = url.lower()
    domain = urlparse(url).netloc.lower()

    # Common reading platforms
    if 'manga' in url_lower or 'manga' in domain:
        tags.add('manga')
    if 'manhwa' in url_lower or 'manhwa' in domain:
        tags.add('manhwa')
    if 'manhua' in url_lower or 'manhua' in domain:
        tags.add('manhua')
    if 'novel' in url_lower or 'lightnovel' in url_lower or 'novelupdates' in domain:
        tags.add('novel')
    if 'webtoon' in url_lower or 'comic' in url_lower:
        tags.add('webtoon')
    if 'fanfic' in url_lower or 'fanfiction' in url_lower or 'ao3' in domain or 'archiveofourown' in domain:
        tags.add('fanfiction')
    if 'wattpad' in domain:
        tags.add('wattpad')
    if 'arxiv' in domain:
        tags.add('paper')
    if 'medium.com' in domain:
        tags.add('article')
    if 'github.com' in domain:
        tags.add('github')
    if 'youtube.com' in domain or 'youtu.be' in domain:
        tags.add('video')
    if 'reddit.com' in domain:
        tags.add('reddit')
    if 'wikipedia' in domain:
        tags.add('wiki')
    if 'goodreads' in domain:
        tags.add('book')

    # Filter out common noise words
    noise_words = {'home', 'page', 'website', 'site', 'read', 'online', 'free', 'www', 'the', 'and', 'for'}
    tags = {t for t in tags if t not in noise_words}

    return list(tags)[:10]  # Return max 10 tags


def extract_comments(soup, url):
    """Extract comments/reviews from the page."""
    comments = []
    total_count = 0

    try:
        domain = urlparse(url).netloc.lower()

        # NovelUpdates reviews - specific structure
        if 'novelupdates.com' in domain:
            # NovelUpdates uses .w-review for review containers
            review_elements = soup.select('.w-review')

            for el in review_elements[:15]:
                try:
                    # Get author from .w-review-author or similar
                    author = None
                    author_el = el.select_one('.userank a, .w-review-author a, a[href*="/user/"]')
                    if author_el:
                        author = author_el.get_text(strip=True)

                    # Get review text - look for the actual review content div
                    text = None
                    # The review text is usually in a div after the metadata
                    text_el = el.select_one('.w-review-body, .review-text, div[style*="margin"]')
                    if text_el:
                        text = text_el.get_text(strip=True)

                    # If no specific text element, get text but exclude metadata
                    if not text:
                        # Clone element and remove known metadata elements
                        for meta in el.select('.userank, .ur-star-rating, .w-review-actions, script, style'):
                            meta.decompose() if hasattr(meta, 'decompose') else None

                        # Get paragraphs or divs with actual content
                        content_parts = []
                        for p in el.find_all(['p', 'div'], recursive=False):
                            p_text = p.get_text(strip=True)
                            # Skip short metadata-like text
                            if len(p_text) > 50 and not any(skip in p_text.lower() for skip in ['rated it', 'other reviews', 'status:']):
                                content_parts.append(p_text)

                        if content_parts:
                            text = ' '.join(content_parts)

                    # Get date
                    date = None
                    date_el = el.select_one('.w-review-date, time, [class*="date"]')
                    if date_el:
                        date = date_el.get_text(strip=True)

                    if text and len(text) > 30:
                        # Clean up the text - remove common UI fragments
                        skip_phrases = ['write a review', 'leave a review', 'other reviews by this user',
                                       'rated it', 'guidelines', 'you must be', 'register', 'login']
                        if not any(phrase in text.lower()[:100] for phrase in skip_phrases):
                            comments.append({
                                'text': text[:500],
                                'author': author,
                                'date': date
                            })
                except:
                    continue

            # Try alternate NovelUpdates selectors if w-review didn't work
            if not comments:
                # Try looking for review list items
                for el in soup.select('.reviewlist li, #reviewlist li, .reviews-list > div'):
                    try:
                        text = el.get_text(strip=True)
                        if text and len(text) > 50:
                            # Skip if it's UI text
                            if any(skip in text.lower()[:50] for skip in ['write', 'sort', 'filter', 'login']):
                                continue
                            comments.append({
                                'text': text[:500],
                                'author': None,
                                'date': None
                            })
                    except:
                        continue

            # Get total count from NovelUpdates
            count_el = soup.select_one('#reviewshow, .review-count, [class*="review"] [class*="count"]')
            if count_el:
                count_match = re.search(r'(\d+)', count_el.get_text())
                if count_match:
                    total_count = int(count_match.group(1))

        # Generic comment extraction for other sites
        if not comments:
            # Common comment selectors - be more specific
            comment_selectors = [
                '.comment-content', '.comment-text', '.comment-body p',
                '.review-content', '.review-text', '.review-body p',
                'article.comment > p', 'div.comment > p',
            ]

            for selector in comment_selectors:
                try:
                    elements = soup.select(selector)
                    for el in elements[:15]:
                        text = el.get_text(strip=True)
                        # Filter out too short, navigation text, or UI elements
                        if text and len(text) > 30 and len(text) < 2000:
                            # Skip common UI phrases
                            skip_phrases = ['write a', 'leave a', 'log in', 'sign up', 'register', 'guidelines']
                            if any(phrase in text.lower()[:50] for phrase in skip_phrases):
                                continue

                            # Try to find author in parent
                            author = None
                            parent = el.parent
                            if parent:
                                author_selectors = ['.author', '.username', '.user', 'cite', '.name']
                                for auth_sel in author_selectors:
                                    auth_el = parent.select_one(auth_sel)
                                    if auth_el:
                                        author = auth_el.get_text(strip=True)
                                        break

                            comments.append({
                                'text': text[:500],
                                'author': author,
                                'date': None
                            })

                    if comments:
                        break
                except:
                    continue

            # Try to find total comment count
            count_patterns = [
                r'(\d+)\s*comments?',
                r'(\d+)\s*reviews?',
                r'comments?\s*\((\d+)\)',
                r'reviews?\s*\((\d+)\)',
            ]
            page_text = soup.get_text()[:5000]  # Only check first part
            for pattern in count_patterns:
                match = re.search(pattern, page_text, re.IGNORECASE)
                if match:
                    total_count = int(match.group(1))
                    break

        # Remove duplicates - use normalized text comparison
        seen = set()
        unique_comments = []
        for c in comments:
            # Normalize: lowercase, remove extra spaces
            normalized = ' '.join(c['text'].lower().split())[:80]
            if normalized not in seen:
                seen.add(normalized)
                unique_comments.append(c)

        if not total_count:
            total_count = len(unique_comments)

        return {
            'comments': unique_comments[:15],
            'total': total_count
        }

    except Exception as e:
        return {'comments': [], 'total': 0}


@app.route('/api/item/<int:id>/update', methods=['POST'])
def api_update_item(id):
    item = ReadingMaterial.query.get_or_404(id)
    data = request.get_json()

    field = data.get('field')
    value = data.get('value')

    if field == 'title':
        if not value or not value.strip():
            return jsonify({'error': 'Title is required'}), 400
        item.title = value.strip()
    elif field == 'link':
        item.link = value.strip() if value else None
    elif field == 'image_url':
        item.image_url = value.strip() if value else None
    elif field == 'status_id':
        item.status_id = int(value) if value else None
    elif field == 'chapter_current':
        item.chapter_current = max(0, int(value) if value else 0)
    elif field == 'chapter_total':
        item.chapter_total = int(value) if value else None
    elif field == 'notes':
        item.notes = value.strip() if value else None
    elif field == 'tags':
        # value is a list of tag names
        item.tags.clear()
        if value:
            for tag_name in value:
                tag_name = tag_name.strip()
                if tag_name:
                    # Case-insensitive search for existing tag
                    tag = Tag.query.filter(Tag.name.ilike(tag_name)).first()
                    if not tag:
                        tag = Tag(name=tag_name, color=Tag.random_color())
                        db.session.add(tag)
                    item.tags.append(tag)
    else:
        return jsonify({'error': 'Invalid field'}), 400

    db.session.commit()

    return jsonify({
        'success': True,
        'item': {
            'id': item.id,
            'title': item.title,
            'link': item.link,
            'status_id': item.status_id,
            'status_display': item.status_display,
            'status_color': item.status_color,
            'chapter_current': item.chapter_current,
            'chapter_total': item.chapter_total,
            'progress_percent': item.progress_percent,
            'tags': [tag.name for tag in item.tags]
        }
    })


if __name__ == '__main__':
    app.run(debug=True, port=5001, host='0.0.0.0')
