#include "../local_resource_policy.hpp"

#include <cassert>
#include <string>
#include <vector>

using idoly::presentation::local_resources::object_url;

bool accepts(const std::u16string &value) {
    std::vector<uint16_t> units(value.begin(), value.end());
    return object_url(units.data(), units.size());
}

int main() {
    // These four immutable object identities are the HTTP200 thumbnails in
    // diagnostics19, not invented game-account or image upload identifiers.
    const std::u16string observed[] = {
        u"http://127.0.0.1:8080/octo/202050/assetbundle/EiDd9n/1768822424265240",
        u"http://127.0.0.1:8080/octo/202050/assetbundle/yFD8qT/1768822424267701",
        u"http://127.0.0.1:8080/octo/202050/assetbundle/JTAnvR/1768822424398894",
        u"http://127.0.0.1:8080/octo/202050/assetbundle/nTGbK7/1768822424602282",
    };
    for (const auto &url : observed) assert(accepts(url));
    assert(accepts(u"http://127.0.0.1:8080/octo/1/resources/A_-0/1"));
    assert(accepts(u"http://127.0.0.1:8080/octo/2147483647/assetbundle/"
        + std::u16string(128, u'a') + u"/18446744073709551615"));

    const std::u16string denied[] = {
        u"", u"https://127.0.0.1:8080/octo/1/resources/a/1",
        u"HTTP://127.0.0.1:8080/octo/1/resources/a/1",
        u"http://localhost:8080/octo/1/resources/a/1",
        u"http://127.1:8080/octo/1/resources/a/1",
        u"http://2130706433:8080/octo/1/resources/a/1",
        u"http://127.0.0.1/octo/1/resources/a/1",
        u"http://127.0.0.1:80/octo/1/resources/a/1",
        u"http://127.0.0.1:08080/octo/1/resources/a/1",
        u"http://127.0.0.1:8081/octo/1/resources/a/1",
        u"http://127.0.0.1:8080.evil/octo/1/resources/a/1",
        u"http://127.0.0.1:8080@evil/octo/1/resources/a/1",
        u"http://name@127.0.0.1:8080/octo/1/resources/a/1",
        u"http://[::1]:8080/octo/1/resources/a/1",
        u"//127.0.0.1:8080/octo/1/resources/a/1",
        u" http://127.0.0.1:8080/octo/1/resources/a/1",
        u"http://127.0.0.1:8080/octo/1/resources/a/1 ",
        u"http://127.0.0.1:8080//octo/1/resources/a/1",
        u"http://127.0.0.1:8080/octo/0/resources/a/1",
        u"http://127.0.0.1:8080/octo/01/resources/a/1",
        u"http://127.0.0.1:8080/octo/-1/resources/a/1",
        u"http://127.0.0.1:8080/octo/2147483648/resources/a/1",
        u"http://127.0.0.1:8080/octo/1/AssetBundle/a/1",
        u"http://127.0.0.1:8080/octo/1/resource/a/1",
        u"http://127.0.0.1:8080/octo/1/resources//1",
        u"http://127.0.0.1:8080/octo/1/resources/../1",
        u"http://127.0.0.1:8080/octo/1/resources/a.b/1",
        u"http://127.0.0.1:8080/octo/1/resources/%61/1",
        u"http://127.0.0.1:8080/octo/1/resources/a/0",
        u"http://127.0.0.1:8080/octo/1/resources/a/01",
        u"http://127.0.0.1:8080/octo/1/resources/a/-1",
        u"http://127.0.0.1:8080/octo/1/resources/a/18446744073709551616",
        u"http://127.0.0.1:8080/octo/1/resources/a/1/",
        u"http://127.0.0.1:8080/octo/1/resources/a/1?alt=media",
        u"http://127.0.0.1:8080/octo/1/resources/a/1#x",
        u"http://127.0.0.1:8080/master/a",
        u"http://127.0.0.1:8080/v2/pub/a/212/v/205051/list/1089",
        u"http://127.0.0.1:8080/diagnostics/client",
        u"https://d2ilil7yh5oi1v.cloudfront.net/solis-1-resources/a?generation=1&alt=media",
    };
    for (const auto &url : denied) assert(!accepts(url));
    assert(!accepts(u"http://127.0.0.1:8080/octo/1/resources/" + std::u16string(129, u'a') + u"/1"));
    assert(!accepts(u"http://127.0.0.1:8080/octo/1/resources/\uac00/1"));
    assert(!accepts(u"http://127.0.0.1:8080/octo/1/resources/" + std::u16string(1, char16_t(0xd800)) + u"/1"));
    auto embedded = observed[0]; embedded.insert(embedded.begin() + 8, u'\0');
    assert(!accepts(embedded));
    assert(!object_url(nullptr, 50));
}
