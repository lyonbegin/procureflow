"""Non-mutating, external-URL-restricted headless browser contract tests."""
import pytest

from browser_diagnostics import validate_id, safe_request


class Req:
    def __init__(self,method,url):
        self.method=method
        self.url=url


class Route:
    def __init__(self,method,url):
        self.request=Req(method,url)
        self.result=None
    def continue_(self):
        self.result="allowed"
    def abort(self,error_code):
        self.result="blocked:"+error_code


@pytest.mark.parametrize("method,url,expected",[
    ("GET","https://www.k-apt.go.kr/bid/bidList.do","allowed"),
    ("GET","https://www.k-apt.go.kr/bid/bidDetail.do?bidNum=20261020165014951","allowed"),
    ("POST","https://www.k-apt.go.kr/bid/bidDetail.do","allowed"),
    ("POST","https://www.k-apt.go.kr/bid/bidList.do","allowed"),
    ("POST","https://www.k-apt.go.kr/bid/submit.do","blocked:blockedbyclient"),
    ("GET","https://www.k-apt.go.kr/login/selLoginForm.do","blocked:blockedbyclient"),
    ("GET","https://www.k-apt.go.kr/bid/bidJoin.do","blocked:blockedbyclient"),
    ("GET","http://www.k-apt.go.kr/bid/bidDetail.do","blocked:blockedbyclient"),
    ("GET","https://www.example.org/","blocked:blockedbyclient"),
    ("DELETE","https://www.k-apt.go.kr/bid/bidDetail.do","blocked:blockedbyclient"),
])
def test_no_non_readonly_requests(method,url,expected):
    route=Route(method,url)
    blocked=[]
    safe_request(route,blocked)
    assert route.result==expected
    assert bool(blocked)==expected.startswith("blocked")


def test_no_arbitrary_browser_targets():
    assert validate_id("20261020165014951")=="20261020165014951"
    with pytest.raises(ValueError):
        validate_id("https://internal.service.local")
    with pytest.raises(ValueError):
        validate_id("../api/jobs")
