// jaipl shapes demo: classes, inheritance, collections
class Shape {
    let name = "shape"
    func area() { return 0 }
    func describe() { return self.name + " with area " + str(self.area()) }
}
class Rect extends Shape {
    let w
    let h
    func new(w, h) {
        self.name = "rectangle"
        self.w = w
        self.h = h
    }
    func area() { return self.w * self.h }
}
class Square extends Rect {
    func new(side) {
        self.name = "square"
        self.w = side
        self.h = side
    }
}
let shapes = [new Rect(3, 4), new Square(5), new Shape()]
for s in shapes {
    print(s.describe())
}
var total = 0
for s in shapes {
    total = total + s.area()
}
print("total area:", total)
print("count:", len(shapes))
