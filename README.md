# WebSentinal

**WebSentinal** is a web crawler focused on crawling web applications and extracting potential attack surfaces such as links, endpoints, and input vectors.

It is built to assist in the **reconnaissance phase** of security testing by mapping out the structure of a target application.

---

## 🚀 Features

- Performs **deep crawling** to extract links, scripts, images, and resources from the target website.
- Discovers different types of **endpoints** such as static, dynamic, hidden and contextual endpoints.
- Full **CLI support** for easy integration into security testing workflows.
- **Rate limiting** to avoid overwhelming the target server and reduce the risk of being blocked.
- Saves the Output in a **structured format(json, txt)** for further analysis and reporting.  

---

## 🛠️ Installation

<b>1. Clone repo</b>
```bash
git clone https://github.com/Mr-Sudheer/Websentinal.git
```
```bash
cd Websentinal
```
<b>2. Install dependencies</b>
```bash
pip install -r requirements.txt
```
```bash
playwright install
```

<b>3. Run the tool</b>
```bash
python Websentinal.py
```

---

## CLI options/flags

```bash
usage: Websentinal.py [-h] -u URL [--depth DEPTH] [--threads THREADS] [--delay DELAY] [--timeout TIMEOUT] [--wordlist WORDLIST] [--no-endpoints] [--no-dynamic] [-o OUTPUT] [--no-save]

options:
  -h, --help           show this help message and exit
  -u, --url URL        Target URL
  --depth DEPTH        Crawl depth (default: 2)
  --threads THREADS    Concurrent threads (default: 15)
  --delay DELAY        Delay between requests in seconds (default: 0)
  --timeout TIMEOUT    Request timeout in seconds (default: 8)
  --wordlist WORDLIST  Path to custom hidden-endpoint wordlist file
  --no-endpoints       Skip endpoint discovery phase
  --no-dynamic         Skip dynamic (Playwright) endpoint scanning
  -o, --output OUTPUT  Output file prefix (default: websentinal)
  --no-save            Don't save output files
```

## CLI Output

```text
C:\Users\senor\AppData\Local\Programs\Python\Python313\python.exe p:/Git/Websentinal/Websentinal/Websentinal.py -u https://mr-sudheer.github.io/
[HEAD] Starting crawl on https://mr-sudheer.github.io/ (depth=2, threads=15)
[OK] Crawl complete in 3.61s — 12 pages | 26 links | 13 scripts | 0 forms | 12 inputs | 9 images
[INFO] Checking if site is JS-heavy...
[HEAD] Starting endpoint discovery...
[OK] Endpoint discovery done in 11.02s — static=1 | dynamic=1 | hidden=2 | contextual=0
  WEBSENTINAL — SUMMARY
Links : 26
Scripts : 13
Images : 9
Resources : 26
Forms : 0
Inputs : 12
Parameters : 0
Comments : 0
  Static Endpoints : 1
  Dynamic Endpoints : 1
  Hidden Endpoints : 2
  Contextual Endpoints : 0
[OK] Saved → websentinal_crawl.json
[OK] Saved → websentinal_crawl.txt
[OK] Saved → websentinal_endpoints.json
[OK] Saved → websentinal_endpoints.txt
```

## Limitations

- Some websites return **403 Forbidden**, which prevents effective crawling.  
- No support for **parallel crawling**.  
- Limited handling of advanced anti-bot protections. 
- No capability to bypass **CAPTCHA** or similar challenges. 

## ⚠️ Disclaimer

This tool is intended for educational and ethical use only. Always obtain proper authorization before using it to test any web application. The author is not responsible for any misuse or damage caused by this tool.

The output sample that I have provided is tested on my own website built using GitHub Pages, which is a static site hosting service. You can visit the site [here](https://mr-sudheer.github.io/).