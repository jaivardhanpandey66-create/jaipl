// Run C++ from jaipl with gpp.
import gpp

print("compiler:", gpp.version())

let r = gpp.run("""
#include <iostream>
#include <vector>
int main() {
    std::vector<int> v{3, 1, 4, 1, 5};
    int total = 0;
    for (int x : v) total += x;
    std::cout << "sum=" << total << std::endl;
    return 0;
}
""")

print("exit code:", r.code)
print("output:", r.out)

let check = gpp.compile("#include <vector>\nint main(){ return 0; }")
print("compiles:", check.ok)
