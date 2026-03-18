from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from urllib.parse import urljoin, quote_plus, urlparse
from urllib.request import Request, urlopen
from difflib import SequenceMatcher
import re

BASE = "https://weebcentral.com"
CHAPTER_SELECTOR = "a[href*='/chapter/'], a[href*='/chapters/']"
SERIES_SELECTOR = "a[href*='/series/']"
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def format_chapter_number(num: float) -> str:
    if num is None:
        return "?"
    if float(num).is_integer():
        return str(int(num))
    return f"{num:.2f}".rstrip("0").rstrip(".")


def extract_chapter_number(title: str, url: str = ""):
    text = normalize_text(title).replace(",", ".")
    patterns = [
        r"(?:cap(?:[íi]tulo)?|chapter|ch)\s*[-:#]?\s*(\d+(?:\.\d+)?)",
        r"\b(\d+(?:\.\d+)?)\b",
    ]

    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                pass

    if url:
        tail = normalize_text(url.rstrip("/").split("/")[-1]).replace("_", " ")

        # First, try explicit chapter-like patterns in the URL slug.
        slug_match = re.search(
            r"(?:cap(?:[íi]tulo)?|chapter|ch)\s*[-:#]?\s*(\d+(?:\.\d+)?)",
            tail,
        )
        if slug_match:
            try:
                return float(slug_match.group(1))
            except ValueError:
                pass

        # Fallback: use the LAST number in slug (many sites prefix IDs before chapter).
        numbers = re.findall(r"(\d+(?:\.\d+)?)", tail)
        if numbers:
            try:
                return float(numbers[-1])
            except ValueError:
                pass

    return None


def chapter_sort_key(chapter: dict):
    number = chapter.get("number")
    if number is None:
        return (1, float("inf"), normalize_text(chapter.get("title", "")))
    return (0, number, normalize_text(chapter.get("title", "")))


def build_full_chapter_list_url(series_url: str):
    try:
        path_parts = [p for p in urlparse(series_url).path.split("/") if p]
    except Exception:
        return None

    if len(path_parts) >= 2 and path_parts[0] == "series":
        series_id = path_parts[1]
        return f"{BASE}/series/{series_id}/full-chapter-list"

    return None


def clean_html_text(raw_html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", raw_html or "")
    return re.sub(r"\s+", " ", text).strip()


def parse_chapters_from_full_list_html(html: str):
    chapters = []
    seen = set()

    anchor_pattern = re.compile(
        r"<a[^>]+href=['\"](?P<href>(?:https?://[^'\"]+)?/chapters/[A-Za-z0-9]+)['\"][^>]*>(?P<title>.*?)</a>",
        flags=re.IGNORECASE | re.DOTALL,
    )

    for match in anchor_pattern.finditer(html or ""):
        href = (match.group("href") or "").strip()
        if not href:
            continue

        full_url = urljoin(BASE, href)
        if full_url in seen:
            continue

        raw_title = clean_html_text(match.group("title") or "")
        number = extract_chapter_number(raw_title, full_url)

        if number is not None:
            title = f"Chapter {format_chapter_number(number)}"
        elif raw_title:
            title = raw_title
        else:
            title = full_url.rsplit("/", 1)[-1]

        chapters.append({"title": title, "url": full_url, "number": number})
        seen.add(full_url)

    chapters.sort(key=chapter_sort_key)
    return chapters


def fetch_full_chapter_list(series_url: str):
    full_list_url = build_full_chapter_list_url(series_url)
    if not full_list_url:
        return []

    try:
        req = Request(full_list_url, headers=DEFAULT_HEADERS)
        with urlopen(req, timeout=60) as response:
            html = response.read().decode("utf-8", errors="ignore")
    except Exception as e:
        print(f"Falha ao carregar lista completa de capítulos: {e}")
        return []

    chapters = parse_chapters_from_full_list_html(html)
    if chapters:
        print(f"Lista completa carregada em {full_list_url}")
    return chapters


def collect_series_links(page):
    items = []
    seen = set()

    try:
        page.wait_for_selector(SERIES_SELECTOR, timeout=8000)
    except PlaywrightTimeoutError:
        return items

    links = page.locator(SERIES_SELECTOR)
    total = links.count()

    for i in range(total):
        link = links.nth(i)
        href = (link.get_attribute("href") or "").strip()
        if not href or "/series/" not in href:
            continue

        full_url = urljoin(BASE, href).split("?", 1)[0]
        if full_url in seen:
            continue

        title = (link.text_content() or "").strip()
        if not title:
            title = (link.get_attribute("title") or "").strip()
        if not title:
            title = full_url.rstrip("/").rsplit("/", 1)[-1].replace("-", " ")

        items.append({"title": title, "url": full_url})
        seen.add(full_url)

    return items


def score_series(query: str, item: dict) -> int:
    q = normalize_text(query)
    title = normalize_text(item["title"])
    slug = normalize_text(item["url"].rstrip("/").rsplit("/", 1)[-1].replace("-", " "))

    score = 0
    if q == title:
        score += 100
    if q in title:
        score += 70
    if q in slug:
        score += 60

    score += int(similarity(q, title) * 40)
    score += int(similarity(q, slug) * 30)
    return score


def pick_best_series(items, query: str):
    best = None
    for item in items:
        score = score_series(query, item)
        if not best or score > best["score"]:
            best = {"title": item["title"], "url": item["url"], "score": score}
    return best


def find_search_input(page):
    selectors = [
        "input[type='search']",
        "input[placeholder*='earch']",
        "input[name*='earch']",
        "input[aria-label*='earch']",
    ]

    for selector in selectors:
        loc = page.locator(selector)
        if loc.count() > 0:
            return loc.first

    inputs = page.locator("input")
    total = min(inputs.count(), 40)

    for i in range(total):
        inp = inputs.nth(i)
        attrs = " ".join(
            [
                inp.get_attribute("placeholder") or "",
                inp.get_attribute("name") or "",
                inp.get_attribute("aria-label") or "",
                inp.get_attribute("id") or "",
                inp.get_attribute("type") or "",
            ]
        ).lower()
        if "search" in attrs or "manga" in attrs:
            return inp

    return None


def find_manga_url(page, manga_name: str):
    query = manga_name.strip()
    if not query:
        return None

    search_urls = [
        f"{BASE}/search?text={quote_plus(query)}",
        f"{BASE}/search?q={quote_plus(query)}",
        f"{BASE}/search?query={quote_plus(query)}",
        f"{BASE}/series?search={quote_plus(query)}",
    ]

    best = None

    for search_url in search_urls:
        print(f"Tentando busca: {search_url}")
        try:
            page.goto(search_url, wait_until="domcontentloaded", timeout=45000)
        except PlaywrightTimeoutError:
            continue

        page.wait_for_timeout(1500)
        candidate = pick_best_series(collect_series_links(page), query)
        if candidate and (not best or candidate["score"] > best["score"]):
            best = candidate

        if best and best["score"] >= 90:
            break

    if not best or best["score"] < 90:
        print("Tentando busca pela interface do site...")
        try:
            page.goto(BASE, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(1200)

            search_input = find_search_input(page)
            if search_input is not None:
                search_input.click()
                search_input.fill(query)
                search_input.press("Enter")
                page.wait_for_timeout(1800)

                candidate = pick_best_series(collect_series_links(page), query)
                if candidate and (not best or candidate["score"] > best["score"]):
                    best = candidate
        except Exception:
            pass

    if best and best["score"] >= 45:
        return {"title": best["title"], "url": best["url"]}

    return None


def get_chapters(page, series_url: str = ""):
    print("Pegando capítulos...")

    # Prefer a dedicated full list endpoint to avoid missing older chapters.
    if series_url:
        chapters = fetch_full_chapter_list(series_url)
        if chapters:
            numbers = [c["number"] for c in chapters if c["number"] is not None]
            if numbers:
                print(
                    f"Capítulos encontrados: {len(chapters)} | "
                    f"do {format_chapter_number(min(numbers))} ao {format_chapter_number(max(numbers))}"
                )
            else:
                print(f"Capítulos encontrados: {len(chapters)}")
            return chapters

        print("Não consegui carregar a lista completa. Tentando coleta da página atual...")

    try:
        page.wait_for_selector(CHAPTER_SELECTOR, timeout=20000)
    except PlaywrightTimeoutError:
        print("Não foi possível encontrar links de capítulo.")
        return []

    links = page.locator(CHAPTER_SELECTOR)
    chapters = []
    seen = set()

    for i in range(links.count()):
        link = links.nth(i)

        href = link.get_attribute("href") or ""
        if not href:
            continue

        full_url = urljoin(BASE, href)
        if full_url in seen:
            continue

        title = (link.text_content() or "").strip()
        if not title:
            title = full_url.rsplit("/", 1)[-1]

        number = extract_chapter_number(title, full_url)

        chapters.append({"title": title, "url": full_url, "number": number})
        seen.add(full_url)

    chapters.sort(key=chapter_sort_key)

    numbers = [c["number"] for c in chapters if c["number"] is not None]
    if numbers:
        print(
            f"Capítulos encontrados: {len(chapters)} | "
            f"do {format_chapter_number(min(numbers))} ao {format_chapter_number(max(numbers))}"
        )
    else:
        print(f"Capítulos encontrados: {len(chapters)}")

    return chapters


def choose_chapter(chapters, query: str):
    if not chapters:
        return None

    # Lista ordenada: mais antigo -> mais novo
    if not query:
        return chapters[0]

    q = normalize_text(query)

    if q in {"primeiro", "first", "inicio", "início"}:
        return chapters[0]
    if q in {"ultimo", "último", "last", "latest", "recente"}:
        return chapters[-1]

    # Busca numérica exata (evita "1" casar com "1100")
    match = re.search(r"\d+(?:[.,]\d+)?", q)
    if match:
        raw_target = match.group(0).replace(",", ".")
        target = float(raw_target)

        # Prefer exact numeric match from parsed chapter number.
        for chapter in chapters:
            n = chapter.get("number")
            if n is not None and abs(n - target) < 1e-9:
                return chapter

        # Fallback: strict numeric boundary in title/url, avoiding partial matches.
        if "." in raw_target:
            number_pattern = rf"(?<!\d){re.escape(raw_target)}(?!\d)"
        else:
            number_pattern = rf"(?<!\d){re.escape(raw_target)}(?:\.0+)?(?!\d)"

        for chapter in chapters:
            haystack = " ".join(
                [
                    normalize_text(chapter.get("title", "")).replace(",", "."),
                    normalize_text(chapter.get("url", "")).replace(",", "."),
                ]
            )
            if re.search(number_pattern, haystack):
                return chapter

    # Match exato por texto
    for chapter in chapters:
        if normalize_text(chapter["title"]) == q:
            return chapter

    # Fallback por contains
    for chapter in chapters:
        if q in normalize_text(chapter["title"]):
            return chapter

    return None


def get_images(page):
    print("Pegando imagens do capítulo...")

    img_selector = "img[src], img[data-src], img[data-lazy-src]"

    try:
        page.wait_for_selector(img_selector, timeout=15000)
    except PlaywrightTimeoutError:
        print("Nenhuma imagem encontrada.")
        return []

    imgs = page.locator(img_selector)
    images = []
    seen = set()

    for i in range(imgs.count()):
        img = imgs.nth(i)
        src = (
            img.get_attribute("src")
            or img.get_attribute("data-src")
            or img.get_attribute("data-lazy-src")
            or ""
        ).strip()

        if not src or src.startswith("data:"):
            continue

        full_url = urljoin(BASE, src)

        if not full_url.startswith("http"):
            continue

        if full_url in seen:
            continue

        seen.add(full_url)
        images.append(full_url)

    print(f"Páginas encontradas: {len(images)}")
    return images


def main():
    manga_name = input("Nome do mangá (ex: One Piece): ").strip()
    chapter_query = input("Capítulo (número, 'primeiro' ou 'ultimo', Enter = primeiro): ").strip()

    if not manga_name:
        print("Informe o nome do mangá.")
        return

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=80)
        page = browser.new_page()

        try:
            print("Buscando mangá pelo nome...")
            manga = find_manga_url(page, manga_name)

            if not manga:
                input(f"\nMangá '{manga_name}' não encontrado. Pressione Enter para sair...")
                return

            print(f"\nMangá encontrado: {manga['title']}")
            print(f"URL: {manga['url']}")

            page.goto(manga["url"], wait_until="domcontentloaded", timeout=60000)

            chapters = get_chapters(page, manga["url"])
            if not chapters:
                input("\nNenhum capítulo encontrado. Pressione Enter para sair...")
                return

            print(f"Total de capítulos no site: {len(chapters)}")

            chapter = choose_chapter(chapters, chapter_query)
            if not chapter:
                print(f"\nCapítulo '{chapter_query}' não encontrado.")
                print("Exemplos disponíveis:")
                for c in chapters[:20]:
                    print(f"- {c['title']}")
                input("\nPressione Enter para sair...")
                return

            print(f"\nAbrindo: {chapter['title']}")
            page.goto(chapter["url"], wait_until="domcontentloaded", timeout=60000)

            images = get_images(page)

            print("\nIMAGENS:\n")
            for i, img in enumerate(images, start=1):
                print(f"{i:03d} - {img}")

            input("\nPressione Enter para fechar o navegador...")

        except Exception as e:
            input(f"\nErro: {e}\nPressione Enter para sair...")

        finally:
            browser.close()


if __name__ == "__main__":
    main()