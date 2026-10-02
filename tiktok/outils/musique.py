"""Musique de fond originale : piano doux + cordes, écrite note par note, rendue avec FluidSynth.

Banque de sons : MuseScore General HQ (licence MIT ; piano « Splendid Grand » domaine public,
cordes VSCO 2 CE en CC0). Rien d'échantillonné d'une œuvre existante : usage commercial libre.

Usage : python3 musique.py sortie.mid [graine] [duree_cible_secondes]
Le tempo s'ajuste pour que les 18 mesures couvrent la durée voulue.
"""
import random
import sys

import mido

TEMPO_BPM = 64
TPB = 480                      # ticks par noire
MESURE = 4 * TPB

# Grille d'accords (une mesure chacun) : la mineur, montée, résolution.
GRILLE = ["Am", "F", "C", "G", "Am", "F", "C", "E",
          "F", "G", "Em", "Am", "Dm", "G", "C", "E",
          "Am", "Am9"]

ACCORDS = {  # fondamentale (octave 2) puis notes du voicing main gauche
    "Am": (45, [45, 52, 57, 60, 64]),
    "Am9": (45, [45, 52, 59, 60, 64]),
    "F": (41, [41, 48, 53, 57, 60]),
    "C": (48, [48, 55, 60, 64, 67]),
    "G": (43, [43, 50, 55, 59, 62]),
    "E": (40, [40, 47, 52, 56, 59]),
    "Em": (40, [40, 47, 52, 55, 59]),
    "Dm": (38, [38, 45, 50, 53, 57]),
}

# Mélodie : (mesure, temps de départ, durée en temps, note MIDI)
N = {"G4": 67, "G#4": 68, "A4": 69, "B4": 71, "C5": 72, "D5": 74, "E5": 76, "F5": 77, "G5": 79}
MELODIE = [
    (5, 0, 2, "E5"), (5, 2, 1, "D5"), (5, 3, 1, "C5"),
    (6, 0, 2, "C5"), (6, 2, 2, "A4"),
    (7, 0, 1.5, "G4"), (7, 1.5, .5, "A4"), (7, 2, 2, "C5"),
    (8, 0, 3, "B4"), (8, 3, 1, "G#4"),
    (9, 0, 2, "A4"), (9, 2, 1, "C5"), (9, 3, 1, "F5"),
    (10, 0, 2, "E5"), (10, 2, 2, "D5"),
    (11, 0, 1.5, "E5"), (11, 1.5, .5, "G5"), (11, 2, 2, "E5"),
    (12, 0, 3, "C5"), (12, 3, 1, "B4"),
    (13, 0, 2, "A4"), (13, 2, 2, "F5"),
    (14, 0, 2, "D5"), (14, 2, 1, "B4"), (14, 3, 1, "D5"),
    (15, 0, 2, "E5"), (15, 2, 2, "C5"),
    (16, 0, 2, "B4"), (16, 2, 2, "G#4"),
    (17, 0, 4, "A4"),
    (18, 0, 4, "E5"),
]


def composer(chemin: str, graine: int = 7, duree: float | None = None) -> None:
    global TEMPO_BPM
    if duree:
        # 18 mesures de 4 temps, plus 4,5 s de résonance à la fin
        TEMPO_BPM = round(18 * 4 * 60 / max(duree - 4.5, 30), 2)
    rnd = random.Random(graine)
    evts = {0: [], 1: [], 2: []}   # piano main gauche, piano main droite, cordes

    def note(piste, canal, debut, duree, hauteur, vel):
        j = rnd.randint(-8, 8) if debut > 0 else 0
        v = max(1, min(127, vel + rnd.randint(-5, 5)))
        evts[piste].append((max(0, debut + j), mido.Message("note_on", channel=canal, note=hauteur, velocity=v)))
        evts[piste].append((debut + j + duree, mido.Message("note_off", channel=canal, note=hauteur, velocity=0)))

    for m, nom in enumerate(GRILLE):
        t0 = m * MESURE
        basse, voix = ACCORDS[nom]
        # Main gauche : arpège en croches, montée puis descente, pédale tenue sur la mesure.
        motif = [voix[0], voix[1], voix[2], voix[3], voix[4], voix[3], voix[2], voix[1]]
        intensite = 38 if m < 4 else 44 if m < 8 else 50 if m < 16 else 44
        if m == len(GRILLE) - 1:
            motif = motif[:5]
        for k, h in enumerate(motif):
            note(0, 0, t0 + k * TPB // 2, TPB * 2, h, intensite - (6 if k % 2 else 0))
        evts[0].append((t0, mido.Message("control_change", channel=0, control=64, value=100)))
        evts[0].append((t0 + MESURE - 20, mido.Message("control_change", channel=0, control=64, value=0)))
        # Cordes : accord tenu à partir de la 2e partie, crescendo puis retour au calme.
        if m >= 8:
            vel = {8: 28, 9: 30, 10: 34, 11: 38, 12: 42, 13: 46, 14: 50, 15: 54, 16: 52, 17: 44}[m]
            for h in (basse, voix[2], voix[3], voix[4]):
                note(2, 1, t0, MESURE - 10, h, vel)

    for (m, temps, duree, nom) in MELODIE:
        debut = (m - 1) * MESURE + int(temps * TPB)
        note(1, 0, debut, int(duree * TPB) - 20, N[nom], 58 if m < 9 else 64 if m < 16 else 52)

    mid = mido.MidiFile(ticks_per_beat=TPB)
    tete = mido.MidiTrack()
    tete.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(TEMPO_BPM)))
    tete.append(mido.Message("program_change", channel=0, program=0, time=0))     # piano
    tete.append(mido.Message("program_change", channel=1, program=48, time=0))    # ensemble de cordes
    tete.append(mido.Message("control_change", channel=1, control=7, value=78, time=0))
    tete.append(mido.Message("control_change", channel=1, control=91, value=110, time=0))
    tete.append(mido.Message("control_change", channel=0, control=91, value=90, time=0))
    mid.tracks.append(tete)
    for piste in (0, 1, 2):
        tr = mido.MidiTrack()
        maintenant = 0
        for t, msg in sorted(evts[piste], key=lambda x: (x[0], x[1].type == "note_on")):
            tr.append(msg.copy(time=t - maintenant))
            maintenant = t
        mid.tracks.append(tr)
    fin = mid.tracks[1]
    fin.append(mido.Message("control_change", channel=0, control=64, value=0, time=int(4.5 * TPB * TEMPO_BPM / 60)))
    mid.save(chemin)


if __name__ == "__main__":
    composer(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 7,
             float(sys.argv[3]) if len(sys.argv) > 3 else None)
