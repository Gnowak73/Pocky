package utils

import (
	"github.com/lucasb-eyer/go-colorful"
)

type number interface {
	// any type whose underlying type is an int or float64 is a number
	~int | ~float64
}

func Clamp[T number](x, min, max T) T {
	// given a number, we clamp it between a min and a max
	if x < min {
		return min
	}
	if x > max {
		return max
	}
	return x
}

func BlendHex(a, b string, t float64) string {
	// after finding the hex value for a color, we make two
	// colors, which are structs. We then blend the colors using the
	// corresponding Blendd function after clamping an interpolation variable
	// between 0 and 1.
	c1, err1 := colorful.Hex(a)
	c2, err2 := colorful.Hex(b)
	if err1 != nil {
		c1 = colorful.Color{}
	}
	if err2 != nil {
		c2 = colorful.Color{}
	}
	t = Clamp(t, 0, 1)
	return c1.BlendHcl(c2, t).Hex()
}
