"""dork generator — all variants: generic, HQ, CMS, country, file, SQLi, error-based, exposed, ecom, admin."""
import random
from pathlib import Path


FILE_TYPES = ["sql", "env", "bak", "log", "txt", "csv", "xml", "json", "zip", "gz"]
CMS_LIST = ["wordpress", "joomla", "drupal", "magento", "prestashop",
            "opencart", "woocommerce", "shopify", "laravel", "django",
            "bitrix", "typo3", "concrete5", "ghost", "strapi", "silverstripe"]
COUNTRIES = ["in", "us", "uk", "ru", "br", "id", "tr", "pk", "bd", "ng",
             "de", "fr", "it", "es", "nl", "se", "jp", "kr", "au", "ca",
             "mx", "ar", "eg", "sa", "ae", "th", "vn", "my", "ph", "za",
             "no", "dk", "fi", "pl", "ua"]

GENERIC_TEMPLATES = [
    'inurl:"{kw}"',
    'intitle:"{kw}"',
    'intext:"{kw}"',
    'site:{tld} inurl:"{kw}"',
    'inurl:"{kw}" ext:php',
    'inurl:"{kw}" ext:asp',
    'inurl:"{kw}" ext:aspx',
    'inurl:"{kw}" ext:jsp',
]

SQLI_TEMPLATES = [
    'inurl:"{kw}.php?id="',
    'inurl:"{kw}.asp?id="',
    'inurl:"{kw}.aspx?id="',
    'inurl:"{kw}.jsp?id="',
    'inurl:"{kw}.php?cat="',
    'inurl:"{kw}.php?product="',
    'inurl:"{kw}.php?page="',
    'inurl:"{kw}.php?item="',
]

FILE_TEMPLATES = [
    'site:{tld} ext:{ft}',
    'site:{tld} inurl:"{kw}" ext:{ft}',
    'site:{tld} intitle:index.of ext:{ft}',
]

CMS_TEMPLATES = [
    'inurl:"{kw}" "wp-content"',
    'inurl:"{kw}" "wp-includes"',
    'inurl:"{kw}" "components/com_"',
    'inurl:"{kw}" "sites/default/files"',
    'inurl:"{kw}" "skin/frontend"',
    'inurl:"{kw}" "modules/"',
]

COUNTRY_TEMPLATES = [
    'inurl:"{kw}" site:{tld}',
    'inurl:"{kw}.php?id=" site:{tld}',
    'site:{tld} inurl:"{kw}"',
]

# error-based: pages leaking DB error messages (defensive recon: find
# verbose error pages so they can be fixed)
HQ_ERROR_TEMPLATES = [
    'inurl:"{kw}.php?id=" intext:"You have an error in your SQL syntax"',
    'inurl:"{kw}.php?id=" intext:"mysql_fetch"',
    'inurl:"{kw}.php?id=" intext:"ODBC"',
    'inurl:"{kw}.php?id=" intext:"PostgreSQL"',
    'inurl:"{kw}.php?id=" intext:"ORA-"',
    'inurl:"{kw}.php?id=" intext:"JDBC"',
    'inurl:"{kw}.php?id=" intext:"SQLite"',
    'inurl:"{kw}.asp?id=" intext:"You have an error in your SQL syntax"',
    'inurl:"{kw}.aspx?id=" intext:"SqlException"',
    'inurl:"{kw}.php?cat=" intext:"mysql_num_rows"',
    'inurl:"{kw}.php?product=" intext:"Warning: mysql_"',
    'inurl:"{kw}.jsp?id=" intext:"SQLException"',
]

# accidentally exposed files/dirs (defensive recon: find leaks to close)
EXPOSED_TEMPLATES = [
    'inurl:"{kw}" ext:sql',
    'intitle:"index of" "{kw}"',
    'inurl:"{kw}" ".env"',
    'inurl:"{kw}" ".git"',
    'inurl:"{kw}" ext:bak',
    'inurl:"{kw}" ext:old',
    'inurl:"{kw}" ext:log',
    'inurl:"{kw}" "wp-config.php.bak"',
    'site:{tld} inurl:"{kw}" ext:sql',
    'site:{tld} intitle:"index of" "{kw}"',
]

# generic shopping pages (product/cart/checkout — never card-data targeted)
ECOM_TEMPLATES = [
    'inurl:"{kw}" inurl:product.php?id=',
    'inurl:"{kw}" inurl:cart.php?',
    'inurl:"{kw}" inurl:checkout',
    'inurl:"{kw}" "add to cart" inurl:item.php?id=',
    'inurl:"{kw}" inurl:shop.php?id=',
    'inurl:"{kw}" inurl:category.php?id=',
]

ADMIN_TEMPLATES = [
    'inurl:"{kw}" inurl:admin/login.php',
    'inurl:"{kw}" intitle:"admin panel"',
    'inurl:"{kw}" inurl:administrator/',
    'inurl:"{kw}" inurl:admin/index.php',
    'inurl:"{kw}" intitle:"login" inurl:admin',
]


class DorkGen:
    def __init__(self, cfg, logger):
        self.cfg = cfg
        self.log = logger
        self.raw = Path(cfg["paths"]["raw"])

    def _write(self, name, items):
        p = self.raw / name
        p.write_text("\n".join(sorted(set(items))))
        self.log.info(f"[dorks] {len(items)} -> {name}")

    def generic(self, keywords: list):
        out = []
        for kw in keywords:
            for t in GENERIC_TEMPLATES:
                out.append(t.format(kw=kw, tld=random.choice(
                    ["com", "net", "org", "io"])))
        self._write("dorks_generic.txt", out)

    def hq_sqli(self, keywords: list):
        out = []
        for kw in keywords:
            for t in SQLI_TEMPLATES:
                out.append(t.format(kw=kw))
        self._write("dorks_sqli.txt", out)

    def hq_error(self, keywords: list):
        out = []
        for kw in keywords:
            for t in HQ_ERROR_TEMPLATES:
                out.append(t.format(kw=kw))
        self._write("dorks_hq_error.txt", out)

    def files(self):
        out = []
        for tld in ["com", "net", "org", "io", "in"]:
            for ft in FILE_TYPES:
                for t in FILE_TEMPLATES:
                    out.append(t.format(tld=tld, ft=ft, kw=ft))
        self._write("dorks_files.txt", out)

    def exposed(self):
        out = []
        seeds = ["backup", "db", "site", "config", "data", "dump"]
        for tld in ["com", "net", "org", "io", "in"]:
            for kw in seeds:
                for t in EXPOSED_TEMPLATES:
                    out.append(t.format(kw=kw, tld=tld))
        self._write("dorks_exposed.txt", out)

    def cms(self, keywords: list):
        out = []
        for kw in keywords:
            for t in CMS_TEMPLATES:
                out.append(t.format(kw=kw))
        self._write("dorks_cms.txt", out)

    def country(self, keywords: list):
        out = []
        for kw in keywords:
            for cc in COUNTRIES:
                for t in COUNTRY_TEMPLATES:
                    out.append(t.format(kw=kw, tld=cc))
        self._write("dorks_country.txt", out)

    def ecom(self, keywords: list):
        out = []
        for kw in keywords:
            for t in ECOM_TEMPLATES:
                out.append(t.format(kw=kw))
        self._write("dorks_ecom.txt", out)

    def admin(self, keywords: list):
        out = []
        for kw in keywords:
            for t in ADMIN_TEMPLATES:
                out.append(t.format(kw=kw))
        self._write("dorks_admin.txt", out)

    def all(self, keywords: list):
        self.generic(keywords)
        self.hq_sqli(keywords)
        self.hq_error(keywords)
        self.files()
        self.exposed()
        self.cms(keywords)
        self.country(keywords)
        self.ecom(keywords)
        self.admin(keywords)
