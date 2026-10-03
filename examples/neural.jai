// A two-layer neural network, written in jaipl, trained to solve XOR.
//
// No libraries, no network, no external tools: everything below is lists,
// floats and loops. Run it with:
//
//     jaipl run neural.jai
//
// The network is 2 inputs -> 2 hidden neurons -> 1 output, using sigmoid
// activations and backpropagation. It starts from a deterministic seed so
// the same run always behaves the same way.

let LEARNING_RATE = 0.5
let EPOCHS = 8000

// ---------------------------------------------------------------- helpers

// Deterministic pseudo-random numbers in [-1, 1]. jaipl has no random()
// builtin yet, and a fixed seed keeps the output reproducible.
let seed = 12345

func rand() {
    seed = (seed * 1103515245 + 12345) % 2147483648
    return (seed * 1.0 / 1073741824.0) - 1.0
}

func sigmoid(x) {
    return 1.0 / (1.0 + exp(-x))
}

// A 2x1 matrix of weights, stored row-major in a flat list.
func make_weights(count) {
    let w = []
    for _i in 0..count {
        push(w, rand())
    }
    return w
}

func forward(x0, x1, w) {
    // Inputs.
    let h1 = sigmoid(w[0] * x0 + w[1] * x1 + w[4])
    let h2 = sigmoid(w[2] * x0 + w[3] * x1 + w[5])
    let y = sigmoid(w[6] * h1 + w[7] * h2 + 1.0)
    return [h1, h2, y]
}

func predict(x0, x1, w) {
    return forward(x0, x1, w)[2]
}

// ---------------------------------------------------------------- training

// w = [w0..w7]
//     w0,w1  input -> hidden 1
//     w2,w3  input -> hidden 2
//     w4     bias -> hidden 1
//     w5     bias -> hidden 2
//     w6,w7  hidden -> output
//     (output bias is fixed at 1.0 to keep this example small)
let w = make_weights(8)

let data = [
    [0.0, 0.0, 0.0],
    [0.0, 1.0, 1.0],
    [1.0, 0.0, 1.0],
    [1.0, 1.0, 0.0],
]

for epoch in 0..EPOCHS {
    let total_error = 0.0

    for row in data {
        let x0 = row[0]
        let x1 = row[1]
        let want = row[2]

        let out = forward(x0, x1, w)
        let h1 = out[0]
        let h2 = out[1]
        let got = out[2]

        // How far off, and the slope of the sigmoid there.
        let delta = (want - got) * got * (1.0 - got)
        total_error = total_error + (want - got) * (want - got)

        // Gradients for the output layer.
        let d_w6 = delta * h1
        let d_w7 = delta * h2

        // Push the error back into the hidden layer.
        let d_h1 = delta * w[6] * h1 * (1.0 - h1)
        let d_h2 = delta * w[7] * h2 * (1.0 - h2)

        w[6] = w[6] + LEARNING_RATE * d_w6
        w[7] = w[7] + LEARNING_RATE * d_w7

        w[0] = w[0] + LEARNING_RATE * d_h1 * x0
        w[1] = w[1] + LEARNING_RATE * d_h1 * x1
        w[4] = w[4] + LEARNING_RATE * d_h1

        w[2] = w[2] + LEARNING_RATE * d_h2 * x0
        w[3] = w[3] + LEARNING_RATE * d_h2 * x1
        w[5] = w[5] + LEARNING_RATE * d_h2
    }

    if epoch % 2000 == 0 {
        print("epoch " + str(epoch) + "  error " + str(round(total_error, 6)))
    }
}

// ---------------------------------------------------------------- results

print("")
print("XOR results (0.0 or 1.0 means the network learned it):")

let all_correct = true
for row in data {
    let got = predict(row[0], row[1], w)
    let shown = round(got, 4)
    print("  " + str(row[0]) + " xor " + str(row[1])
          + "  = " + str(shown) + "   (wanted " + str(row[2]) + ")")
    if round(got, 3) != row[2] {
        all_correct = false
    }
}

print("")
if all_correct {
    print("learned XOR correctly")
} else {
    print("not yet correct - try more epochs or a different seed")
}