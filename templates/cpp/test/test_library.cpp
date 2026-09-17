#include "__MODULE_NAME__/library.hpp"

#include <cassert>

int main() {
    assert(__MODULE_NAME__::add_integers(2, 3) == 5);
    return 0;
}
