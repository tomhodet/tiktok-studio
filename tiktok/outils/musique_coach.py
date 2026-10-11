"""Musique de fond « coach » : pulsation grave, nappe sombre, battement, montée. Écrite note par note
(General MIDI, rendue avec FluidSynth) : aucune œuvre existante.

Usage : python3 musique_coach.py sortie.mid [graine] [duree_cible_secondes]
"""
import random
import sys

import mido

TPB = 480
MESURE = 4 * TPB
GRILLE = ["Dm", "Dm", "Bb", "Bb", "Gm", "Gm", "A", "A", "Dm", "Dm", "Bb", "Bb", "Gm", "A", "Dm", "Dm"]
ACC = {"Dm": (38, [50, 53, 57]), "Bb": (34, [46, 50, 53]), "Gm": (31, [43, 46, 50]), "A": (33, [45, 49, 52])}


def composer(chemin: str, graine: int = 7, duree: float | None = None) -> None:
    bpm = 96.0
    if duree:
        bpm = round(len(GRILLE) * 4 * 60 / max(duree - 2.5, 20), 2)
        bpm = max(80.0, min(132.0, bpm))
    rnd = random.Random(graine)
    pistes = {0: [], 1: [], 2: [], 9: []}

    def note(canal, debut, dur, h, vel):
        v = max(1, min(127, vel + rnd.randint(-4, 4)))
        pistes[canal].append((debut, mido.Message("note_on", channel=canal, note=h, velocity=v)))
        pistes[canal].append((debut + dur, mido.Message("note_off", channel=canal, note=h, velocity=0)))

    n = len(GRILLE)
    for m, nom in enumerate(GRILLE):
        t0 = m * MESURE
        basse, voix = ACC[nom]
        monte = m / max(n - 1, 1)
        # basse synthé : croches pulsées, accent sur les temps
        for k in range(8):
            note(0, t0 + k * TPB // 2, TPB // 2 - 30, basse + (12 if k in (3, 7) and m >= 4 else 0),
                 int(70 + 30 * monte) - (10 if k % 2 else 0))
        # nappe sombre tenue, crescendo
        for h in voix:
            note(1, t0, MESURE - 10, h, int(30 + 45 * monte))
        # battement : grosse caisse temps 1 et 3, caisse claire temps 2 et 4 à partir du milieu, charley
        note(9, t0, TPB // 2, 36, int(85 + 25 * monte))
        note(9, t0 + 2 * TPB, TPB // 2, 36, int(80 + 25 * monte))
        if m >= n // 2:
            note(9, t0 + TPB, TPB // 2, 38, int(60 + 40 * monte))
            note(9, t0 + 3 * TPB, TPB // 2, 38, int(60 + 40 * monte))
        for k in range(8):
            note(9, t0 + k * TPB // 2, TPB // 4, 42, int(28 + 30 * monte) + (12 if k % 2 == 0 else 0))
        # montée finale : roulement sur la dernière mesure
        if m == n - 1:
            for k in range(16):
                note(9, t0 + k * TPB // 4, TPB // 4, 38, 50 + k * 4)
    # coup final
    tf = n * MESURE
    note(9, tf, TPB, 49, 110)
    note(0, tf, 2 * TPB, 38, 110)
    note(1, tf, 3 * TPB, 50, 90)

    mid = mido.MidiFile(ticks_per_beat=TPB)
    tete = mido.MidiTrack()
    tete.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(bpm)))
    tete.append(mido.Message("program_change", channel=0, program=38, time=0))   # basse synthé
    tete.append(mido.Message("program_change", channel=1, program=50, time=0))   # cordes synthé
    tete.append(mido.Message("control_change", channel=1, control=7, value=70, time=0))
    tete.append(mido.Message("control_change", channel=0, control=7, value=100, time=0))
    tete.append(mido.Message("control_change", channel=1, control=91, value=100, time=0))
    mid.tracks.append(tete)
    for canal in (0, 1, 9):
        tr = mido.MidiTrack()
        t = 0
        for debut, msg in sorted(pistes[canal], key=lambda x: (x[0], x[1].type == "note_on")):
            tr.append(msg.copy(time=max(0, debut - t)))
            t = max(t, debut)
        mid.tracks.append(tr)
    mid.save(chemin)


if __name__ == "__main__":
    composer(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 7,
             float(sys.argv[3]) if len(sys.argv) > 3 else None)
