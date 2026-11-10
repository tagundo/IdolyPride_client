// SPDX-License-Identifier: AGPL-3.0-or-later
// Independent C ABI adapter for the attributed upstream live-v5 local rules.
package main

/*
#include <stdint.h>
#include <stdlib.h>
*/
import "C"

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"time"
	"unsafe"

	"github.com/vertesan/solis-server/internal/makino/live"
	"github.com/vertesan/solis-server/internal/proto/papi"
	"github.com/vertesan/solis-server/internal/proto/penum"
	"github.com/vertesan/solis-server/internal/proto/pmaster"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/reflect/protoreflect"
)

const maxBytes = 16 << 20
const (
	ok          = 0
	invalid     = 1
	unsupported = 2
	cancelled   = 3
	internal    = 4
)

type cardMeta struct {
	Index                    int32  `json:"index"`
	Character                string `json:"character_id"`
	Group                    string `json:"group_id"`
	Type                     int32  `json:"type"`
	Attribute                int32  `json:"attribute"`
	Light                    int64  `json:"light_fans"`
	Middle                   int64  `json:"middle_fans"`
	Heavy                    int64  `json:"heavy_fans"`
	CharacterAdvantagePermil int32  `json:"character_advantage_permil,omitempty"`
}

type request struct {
	Version       int                 `json:"input_version"`
	Seed          uint64              `json:"seed"`
	TimeoutMs     int                 `json:"timeout_ms,omitempty"`
	Music         string              `json:"music_id"`
	Proto         map[string][][]byte `json:"proto"`
	Cards         []cardMeta          `json:"cards"`
	SchemaSHA256  string              `json:"schema_sha256,omitempty"`
	MasterVersion string              `json:"master_version,omitempty"`
}

func known(m protoreflect.Message) error {
	if len(m.GetUnknown()) != 0 {
		return fmt.Errorf("unknown protobuf fields in %s", m.Descriptor().FullName())
	}
	var bad error
	m.Range(func(f protoreflect.FieldDescriptor, v protoreflect.Value) bool {
		check := func(v protoreflect.Value) {
			if f.Kind() == protoreflect.MessageKind {
				bad = known(v.Message())
			}
			if f.Kind() == protoreflect.EnumKind && f.Enum().Values().ByNumber(v.Enum()) == nil {
				bad = fmt.Errorf("unknown enum in %s", f.FullName())
			}
		}
		if f.IsList() {
			for i := 0; i < v.List().Len() && bad == nil; i++ {
				check(v.List().Get(i))
			}
		} else {
			check(v)
		}
		return bad == nil
	})
	return bad
}

func readAll[T proto.Message](r request, name string, maximum int, factory func() T) ([]T, error) {
	values := r.Proto[name]
	if len(values) > maximum {
		return nil, fmt.Errorf("too many %s rows", name)
	}
	result := make([]T, 0, len(values))
	for _, raw := range values {
		if len(raw) == 0 || len(raw) > (1<<20) {
			return nil, fmt.Errorf("invalid %s protobuf size", name)
		}
		m := factory()
		if err := proto.Unmarshal(raw, m); err != nil {
			return nil, fmt.Errorf("malformed %s protobuf", name)
		}
		if err := known(m.ProtoReflect()); err != nil {
			return nil, err
		}
		result = append(result, m)
	}
	return result, nil
}

func calculate(raw []byte) ([]byte, int, error) {
	var r request
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&r); err != nil {
		return nil, invalid, fmt.Errorf("invalid live input JSON: %w", err)
	}
	if err := decoder.Decode(new(any)); err != io.EOF {
		return nil, invalid, errors.New("live input must contain one JSON value")
	}
	if r.Version != 1 {
		return nil, invalid, errors.New("unsupported input_version")
	}
	if r.Music == "" || len(r.Cards) < 1 || len(r.Cards) > 10 {
		return nil, invalid, errors.New("music and one to ten prepared card records are required")
	}
	if r.TimeoutMs == 0 {
		r.TimeoutMs = 10000
	}
	if r.TimeoutMs < 1 || r.TimeoutMs > 30000 {
		return nil, invalid, errors.New("timeout_ms must be 1..30000")
	}
	allowed := map[string]bool{"Quest": true, "Setting": true, "Chart": true, "ReferenceChart": true, "UserInfo": true, "QuestPressure": true, "QuestAudienceAdvantage": true, "ComboAdvantage": true, "QuestStaminaConsumption": true, "Skill": true, "SkillEfficacy": true, "SkillTrigger": true, "SkillTarget": true}
	for name := range r.Proto {
		if !allowed[name] {
			return nil, invalid, fmt.Errorf("unsupported protobuf input table: %s", name)
		}
	}
	quests, err := readAll(r, "Quest", 1, func() *pmaster.Quest { return &pmaster.Quest{} })
	if err != nil {
		return nil, invalid, err
	}
	settings, err := readAll(r, "Setting", 1, func() *pmaster.Setting { return &pmaster.Setting{} })
	if err != nil {
		return nil, invalid, err
	}
	pressure, err := readAll(r, "QuestPressure", 1, func() *pmaster.QuestPressure { return &pmaster.QuestPressure{} })
	if err != nil {
		return nil, invalid, err
	}
	if len(quests) != 1 || len(settings) != 1 || len(pressure) != 1 {
		return nil, invalid, errors.New("Quest, Setting and QuestPressure each require exactly one row")
	}
	chart, err := readAll(r, "Chart", 10000, func() *pmaster.MusicChartPattern { return &pmaster.MusicChartPattern{} })
	if err != nil {
		return nil, invalid, err
	}
	reference, err := readAll(r, "ReferenceChart", 10000, func() *pmaster.MusicChartPattern { return &pmaster.MusicChartPattern{} })
	if err != nil {
		return nil, invalid, err
	}
	users, err := readAll(r, "UserInfo", 2, func() *papi.LiveUserInfo { return &papi.LiveUserInfo{} })
	if err != nil {
		return nil, invalid, err
	}
	audience, err := readAll(r, "QuestAudienceAdvantage", 10000, func() *pmaster.QuestAudienceAdvantage { return &pmaster.QuestAudienceAdvantage{} })
	if err != nil {
		return nil, invalid, err
	}
	combo, err := readAll(r, "ComboAdvantage", 1000, func() *pmaster.ComboAdvantage { return &pmaster.ComboAdvantage{} })
	if err != nil {
		return nil, invalid, err
	}
	stamina, err := readAll(r, "QuestStaminaConsumption", 1000, func() *pmaster.QuestStaminaConsumption { return &pmaster.QuestStaminaConsumption{} })
	if err != nil {
		return nil, invalid, err
	}
	skills, err := readAll(r, "Skill", 1024, func() *pmaster.Skill { return &pmaster.Skill{} })
	if err != nil {
		return nil, invalid, err
	}
	efficacies, err := readAll(r, "SkillEfficacy", 16384, func() *pmaster.SkillEfficacy { return &pmaster.SkillEfficacy{} })
	if err != nil {
		return nil, invalid, err
	}
	triggers, err := readAll(r, "SkillTrigger", 1024, func() *pmaster.SkillTrigger { return &pmaster.SkillTrigger{} })
	if err != nil {
		return nil, invalid, err
	}
	targets, err := readAll(r, "SkillTarget", 1024, func() *pmaster.SkillTarget { return &pmaster.SkillTarget{} })
	if err != nil {
		return nil, invalid, err
	}
	coefficient, err := live.BeatScoreCoefficientPermil(r.Music, reference, chart)
	if err != nil {
		return nil, invalid, err
	}
	in := &live.Input{Quest: quests[0], Setting: settings[0], Pressure: pressure[0], Chart: chart, Users: users, AudienceAdvantages: audience, ComboAdvantages: combo, StaminaConsumption: stamina, Seed: r.Seed, BeatScoreCoefficientPermil: coefficient,
		Cards: map[int32]live.CardData{}, Skills: map[string]*pmaster.Skill{}, Efficacies: map[string]*pmaster.SkillEfficacy{}, Triggers: map[string]*pmaster.SkillTrigger{}, Targets: map[string]*pmaster.SkillTarget{}}
	for _, m := range skills {
		if m.Id == "" || in.Skills[m.Id] != nil {
			return nil, invalid, errors.New("duplicate or empty Skill id")
		}
		in.Skills[m.Id] = m
	}
	for _, m := range efficacies {
		if m.Id == "" || in.Efficacies[m.Id] != nil {
			return nil, invalid, errors.New("duplicate or empty SkillEfficacy id")
		}
		in.Efficacies[m.Id] = m
	}
	for _, m := range triggers {
		if m.Id == "" || in.Triggers[m.Id] != nil {
			return nil, invalid, errors.New("duplicate or empty SkillTrigger id")
		}
		in.Triggers[m.Id] = m
	}
	for _, m := range targets {
		if m.Id == "" || in.Targets[m.Id] != nil {
			return nil, invalid, errors.New("duplicate or empty SkillTarget id")
		}
		in.Targets[m.Id] = m
	}
	for _, c := range r.Cards {
		if c.Index < 1 || c.Index > 10 || c.Character == "" || c.Type < 1 || c.Type > 3 || c.Attribute < 1 || c.Attribute > 3 || c.Light < 0 || c.Middle < 0 || c.Heavy < 0 || c.CharacterAdvantagePermil < 0 || c.CharacterAdvantagePermil > 1000000 {
			return nil, invalid, errors.New("invalid prepared card metadata")
		}
		if _, exists := in.Cards[c.Index]; exists {
			return nil, invalid, errors.New("duplicate card metadata index")
		}
		in.Cards[c.Index] = live.CardData{CharacterID: c.Character, GroupID: c.Group, Type: penum.CardType(c.Type), Attribute: penum.AttributeType(c.Attribute), LightFans: c.Light, MiddleFans: c.Middle, HeavyFans: c.Heavy, CharacterAdvantagePermil: c.CharacterAdvantagePermil}
	}
	var actors []live.CardData
	var display []*papi.LiveDeckCard
	seen := map[int32]bool{}
	for _, u := range users {
		for _, c := range u.GetUserDeck().GetCards() {
			data, exists := in.Cards[c.Index]
			if !exists || seen[c.Index] {
				return nil, invalid, errors.New("prepared actor indices do not match metadata")
			}
			seen[c.Index] = true
			actors = append(actors, data)
			display = append(display, c)
		}
	}
	if len(seen) != len(in.Cards) {
		return nil, invalid, errors.New("unused card metadata")
	}
	allocated, err := live.AllocateAudience(actors, quests[0].MaxCapacity, settings[0])
	if err != nil {
		return nil, invalid, err
	}
	for i, c := range display {
		c.AudienceAmount = allocated[i]
	}
	ctx, cancel := context.WithTimeout(context.Background(), time.Duration(r.TimeoutMs)*time.Millisecond)
	defer cancel()
	result, err := live.Simulate(ctx, in)
	if err != nil {
		var missing *live.UnsupportedError
		if errors.As(err, &missing) {
			return nil, unsupported, err
		}
		if errors.Is(err, context.Canceled) || errors.Is(err, context.DeadlineExceeded) {
			return nil, cancelled, errors.New("local live calculation deadline exceeded")
		}
		return nil, invalid, err
	}
	// This library does not provide detail-log storage or the Analyze service.
	result.DetailLogId = ""
	result.IsDisplayDetailAvailable = false
	out, err := proto.MarshalOptions{Deterministic: true}.Marshal(result)
	if err != nil {
		return nil, internal, errors.New("cannot serialize local live result")
	}
	if len(out) > maxBytes {
		return nil, invalid, errors.New("local live result exceeds size limit")
	}
	return out, ok, nil
}

//export IdolyLiveABIVersion
func IdolyLiveABIVersion() C.uint32_t { return 1 }

//export IdolyLiveFree
func IdolyLiveFree(p unsafe.Pointer) { C.free(p) }

//export IdolyLiveSimulate
func IdolyLiveSimulate(input unsafe.Pointer, inputLen C.size_t, output *unsafe.Pointer, outputLen *C.size_t, failure *unsafe.Pointer, failureLen *C.size_t) (status C.int) {
	if output == nil || outputLen == nil || failure == nil || failureLen == nil {
		return invalid
	}
	*output = nil
	*outputLen = 0
	*failure = nil
	*failureLen = 0
	setError := func(message string) {
		raw := []byte(message)
		*failure = C.CBytes(raw)
		*failureLen = C.size_t(len(raw))
	}
	defer func() {
		if recover() != nil {
			if *output != nil {
				C.free(*output)
				*output = nil
				*outputLen = 0
			}
			if *failure != nil {
				C.free(*failure)
			}
			setError("local live calculation panic")
			status = internal
		}
	}()
	if input == nil || inputLen == 0 || inputLen > maxBytes {
		setError("live input size must be 1..16777216 bytes")
		return invalid
	}
	out, code, err := calculate(C.GoBytes(input, C.int(inputLen)))
	if err != nil {
		setError(err.Error())
		return C.int(code)
	}
	*output = C.CBytes(out)
	*outputLen = C.size_t(len(out))
	return ok
}

func main() {}
