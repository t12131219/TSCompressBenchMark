// Copyright 2026 TSDataCompressBenchMark contributors.
// SPDX-License-Identifier: Apache-2.0

package main

import (
	"bufio"
	"encoding/hex"
	"fmt"
	"io"
	"math"
	"os"

	"github.com/prometheus/prometheus/tsdb/chunkenc"
)

func fail(err error) {
	fmt.Fprintln(os.Stderr, err)
	os.Exit(2)
}

func main() {
	if len(os.Args) != 2 {
		fail(fmt.Errorf("usage: xor2_oracle encode|decode"))
	}
	input := bufio.NewReader(os.Stdin)
	switch os.Args[1] {
	case "encode":
		chunk := chunkenc.NewXOR2Chunk()
		appender, err := chunk.Appender()
		if err != nil {
			fail(err)
		}
		for {
			var startTimestamp, timestamp int64
			var valueBits uint64
			_, err = fmt.Fscan(input, &startTimestamp, &timestamp, &valueBits)
			if err == io.EOF {
				break
			}
			if err != nil {
				fail(err)
			}
			appender.Append(startTimestamp, timestamp, math.Float64frombits(valueBits))
		}
		fmt.Println(hex.EncodeToString(chunk.Bytes()))
	case "decode":
		var encodedHex string
		if _, err := fmt.Fscan(input, &encodedHex); err != nil {
			fail(err)
		}
		encoded, err := hex.DecodeString(encodedHex)
		if err != nil {
			fail(err)
		}
		chunk, err := chunkenc.FromData(chunkenc.EncXOR2, encoded)
		if err != nil {
			fail(err)
		}
		iterator := chunk.Iterator(nil)
		for iterator.Next() != chunkenc.ValNone {
			timestamp, value := iterator.At()
			fmt.Printf("%d\t%d\t%016x\n", iterator.AtST(), timestamp, math.Float64bits(value))
		}
		if err := iterator.Err(); err != nil {
			fail(err)
		}
	default:
		fail(fmt.Errorf("unknown mode %q", os.Args[1]))
	}
}
